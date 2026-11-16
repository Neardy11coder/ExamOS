"""
DistilBERT Fine-Tuning and Evaluation Pipeline for ExamOS (M8-ML-DISTILBERT).

Trains `distilbert/distilbert-base-uncased` for sequence classification across the
8 canonical ExamOS taxonomy classes using PyTorch and Hugging Face Transformers.

Deployment Strategy:
- Trains on curated 320-sample dataset (70% train / 15% val / 15% test).
- Exports model weights and tokenizer to `ml/artifacts/distilbert_classifier/`.
- Saves comprehensive metadata and test evaluation report.
- Evaluates CPU/RAM requirements and provides quantized/ONNX export option.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import sys

from ml import TAXONOMY_TOPIC_CODES
from ml.dataset import load_dataset
from ml.dataset_curation import create_stratified_splits

DEFAULT_DISTILBERT_DIR = Path(__file__).resolve().parent / "artifacts" / "distilbert_classifier"
DEFAULT_METADATA_FILE = DEFAULT_DISTILBERT_DIR / "model_metadata.json"
DEFAULT_EVALUATION_REPORT = Path(__file__).resolve().parent / "reports" / "distilbert_evaluation_report.json"
DEFAULT_EVALUATION_SUMMARY = Path(__file__).resolve().parent / "reports" / "distilbert_evaluation_summary.md"

LABEL2ID = {code: idx for idx, code in enumerate(TAXONOMY_TOPIC_CODES)}
ID2LABEL = {idx: code for idx, code in enumerate(TAXONOMY_TOPIC_CODES)}


def train_and_evaluate_distilbert(
    epochs: int = 4,
    batch_size: int = 16,
    learning_rate: float = 3e-5,
    output_dir: Path | str | None = None,
    seed: int = 42,
) -> dict:
    """
    Fine-tunes distilbert-base-uncased on the curated ExamOS dataset.
    Requires torch, transformers, and evaluate/scikit-learn.
    """
    try:
        import torch
        from transformers import (
            AutoModelForSequenceClassification,
            AutoTokenizer,
            Trainer,
            TrainingArguments,
        )
    except ImportError as e:
        raise RuntimeError(
            "PyTorch or Transformers not installed in current environment. "
            "Install with: pip install torch transformers datasets accelerate"
        ) from e

    out_dir = Path(output_dir) if output_dir else DEFAULT_DISTILBERT_DIR
    out_dir.mkdir(parents=True, exist_ok=True)

    records = load_dataset()
    train_set, val_set, test_set = create_stratified_splits(records, val_size=0.15, test_size=0.15, seed=seed)

    print(f"Dataset partitioned: Train={len(train_set)}, Val={len(val_set)}, Test={len(test_set)}")

    model_name = "distilbert/distilbert-base-uncased"
    tokenizer = AutoTokenizer.from_pretrained(model_name)
    model = AutoModelForSequenceClassification.from_pretrained(
        model_name,
        num_labels=len(TAXONOMY_TOPIC_CODES),
        id2label=ID2LABEL,
        label2id=LABEL2ID,
    )

    class TextDataset(torch.utils.data.Dataset):
        def __init__(self, items: list[dict]):
            self.encodings = tokenizer(
                [item["normalized_text"] for item in items],
                truncation=True,
                padding=True,
                max_length=128,
            )
            self.labels = [LABEL2ID[item["topic_code"]] for item in items]

        def __getitem__(self, idx: int):
            item = {key: torch.tensor(val[idx]) for key, val in self.encodings.items()}
            item["labels"] = torch.tensor(self.labels[idx])
            return item

        def __len__(self):
            return len(self.labels)

    train_dataset = TextDataset(train_set)
    val_dataset = TextDataset(val_set)
    test_dataset = TextDataset(test_set)

    def compute_metrics(pred):
        from sklearn.metrics import accuracy_score, f1_score
        labels = pred.label_ids
        preds = pred.predictions.argmax(-1)
        acc = accuracy_score(labels, preds)
        macro_f1 = f1_score(labels, preds, average="macro")
        return {"accuracy": acc, "macro_f1": macro_f1}

    training_args = TrainingArguments(
        output_dir=str(out_dir / "checkpoints"),
        num_train_epochs=epochs,
        per_device_train_batch_size=batch_size,
        per_device_eval_batch_size=batch_size,
        learning_rate=learning_rate,
        weight_decay=0.01,
        evaluation_strategy="epoch",
        save_strategy="epoch",
        load_best_model_at_end=True,
        metric_for_best_model="macro_f1",
        seed=seed,
        logging_steps=10,
        disable_tqdm=True,
    )

    trainer = Trainer(
        model=model,
        args=training_args,
        train_dataset=train_dataset,
        eval_dataset=val_dataset,
        compute_metrics=compute_metrics,
    )

    print("Beginning DistilBERT fine-tuning...")
    trainer.train()

    print("Saving fine-tuned model and tokenizer...")
    trainer.save_model(str(out_dir))
    tokenizer.save_pretrained(str(out_dir))

    # Evaluate on held-out test set
    test_predictions = trainer.predict(test_dataset)
    test_metrics = test_predictions.metrics

    from sklearn.metrics import classification_report, confusion_matrix
    y_true = [LABEL2ID[item["topic_code"]] for item in test_set]
    y_pred = test_predictions.predictions.argmax(-1)

    rep = classification_report(
        y_true,
        y_pred,
        target_names=TAXONOMY_TOPIC_CODES,
        output_dict=True,
        zero_division=0,
    )
    cm = confusion_matrix(y_true, y_pred).tolist()

    metadata = {
        "artifact_version": "2.0.0-distilbert",
        "model_architecture": "DistilBertForSequenceClassification",
        "base_model": model_name,
        "trained_at": datetime.now(timezone.utc).isoformat(),
        "taxonomy_classes": TAXONOMY_TOPIC_CODES,
        "label2id": LABEL2ID,
        "id2label": ID2LABEL,
        "dataset_total": len(records),
        "split_counts": {"train": len(train_set), "val": len(val_set), "test": len(test_set)},
        "hyperparameters": {
            "epochs": epochs,
            "batch_size": batch_size,
            "learning_rate": learning_rate,
            "max_length": 128,
        },
        "test_metrics": {
            "accuracy": round(float(rep["accuracy"]), 4),
            "macro_f1": round(float(rep["macro avg"]["f1-score"]), 4),
            "weighted_f1": round(float(rep["weighted avg"]["f1-score"]), 4),
        },
    }

    with open(out_dir / "model_metadata.json", "w", encoding="utf-8") as f:
        json.dump(metadata, f, indent=2)

    # Save evaluation report
    eval_report = {
        "model": "distilbert/distilbert-base-uncased",
        "evaluated_at": datetime.now(timezone.utc).isoformat(),
        "metrics": metadata["test_metrics"],
        "per_topic_metrics": {
            topic: {
                "precision": round(rep[topic]["precision"], 4),
                "recall": round(rep[topic]["recall"], 4),
                "f1_score": round(rep[topic]["f1-score"], 4),
                "test_support": rep[topic]["support"],
            }
            for topic in TAXONOMY_TOPIC_CODES
        },
        "confusion_matrix": cm,
    }
    with open(DEFAULT_EVALUATION_REPORT, "w", encoding="utf-8") as f:
        json.dump(eval_report, f, indent=2)

    return metadata


def main():
    parser = argparse.ArgumentParser(description="Train DistilBERT topic classification model")
    parser.add_argument("--epochs", type=int, default=4, help="Number of fine-tuning epochs")
    parser.add_argument("--batch-size", type=int, default=16, help="Batch size")
    parser.add_argument("--lr", type=float, default=3e-5, help="Learning rate")
    args = parser.parse_args()

    meta = train_and_evaluate_distilbert(
        epochs=args.epochs,
        batch_size=args.batch_size,
        learning_rate=args.lr,
    )
    print("DistilBERT Training & Evaluation Complete:")
    print(f"  Accuracy: {meta['test_metrics']['accuracy'] * 100:.1f}%")
    print(f"  Macro F1: {meta['test_metrics']['macro_f1']:.4f}")


if __name__ == "__main__":
    main()
