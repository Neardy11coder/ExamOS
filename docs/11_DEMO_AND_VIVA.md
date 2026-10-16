# ExamOS — Demonstration Script and Viva Preparation

**Version:** 0.1 · **Status:** Planning guide, update after implementation  
**Purpose:** Present the project's working behavior and explain the OS, DBMS and ML concepts accurately.

> This is a planned demonstration. Mark a scenario as completed only after it works in the implemented system.

## 1. Suggested 8–10 minute demo sequence

### 0:00–0:45 — Project framing

Explain: “ExamOS is an examination platform focused on reliability. The normal exam workflow is supported by database transactions, persisted deadlines, checkpoint recovery and safe finalization. The OS scheduler is a separate educational simulation, and the ML topic classifier is optional.”

State the important boundary: application attempt sessions are not kernel processes.

### 0:45–2:30 — Faculty creates and publishes an exam

1. Sign in using the seeded faculty account.
2. Open the question bank and create or select 3–5 MCQs tagged with different topics.
3. Create a draft exam with duration and instructions.
4. Publish it.
5. Explain that publication freezes a snapshot of prompt/options/correct answer/marks/topic/order, so later bank edits do not rewrite historical results.

### 2:30–4:15 — Student takes the exam

1. Sign in as a student.
2. Start the published exam.
3. Select answers, mark one question for review and navigate between questions.
4. Point out the remaining-time display and save status.
5. Refresh the browser and show that acknowledged answers are restored and the deadline has not reset.
6. Submit and compare the saved result to a hand-calculated score.

Do not spend demo time on a real wait for timeout. Use a controlled test fixture or a short disposable demonstration exam if showing expiry.

### 4:15–5:15 — Reliability test

Choose one or two scenarios that have been implemented and verified:

- Attempt a stale update from a second tab and show the conflict behavior.
- Trigger expiry after the deadline and show the attempt becomes `EXPIRED` on relevant access.
- Retry submission and show the same saved score/outcome is returned.

Explain that elapsed time does not execute application code by itself; lazy finalization or an optional sweep materializes expiry.

### 5:15–6:15 — OS scheduling simulator

Run FCFS, Round Robin and non-preemptive Priority on the same sample workload. Explain the priority convention and show the Gantt chart, waiting time, turnaround time, response time and utilization. Point out that this simulator uses abstract jobs and does not schedule actual browser sessions or OS kernel processes.

### 6:15–7:15 — Database Performance Lab

Run a predefined selective lookup or join scenario on isolated seeded data in indexed and non-indexed variants. Show actual execution plans and measured times. Explain that index benefits depend on selectivity, row counts, cache and the query planner; an index is not guaranteed to be faster.

Never use placeholder timings or imply a benchmark ran if it did not.

### 7:15–8:00 — ML topic suggestion and analytics

Create a question and request a topic suggestion. Accept or override it. If the classifier is unavailable, show the manual fallback. Open a finalized result and point to topic-level performance analytics. Explain that these insights are deterministic aggregates, not ML predictions.

### 8:00–9:00 — Architecture and DBMS evidence

Show the ER diagram, one transaction boundary, relevant constraints/indexes, test suite and actual test output. Mention the persisted deadline, answer revision, finalization transaction, immutable exam snapshot and role checks.

### 9:00–10:00 — Summary

Summarize the project through three concrete claims, backed by evidence:

1. **OS:** a separately implemented scheduling simulator plus checkpoint/recovery concepts in attempt management.
2. **DBMS:** normalized relational schema, constraints, ACID transactions, row-level concurrency handling and real query-plan comparison.
3. **AI/ML:** local supervised topic classifier with held-out evaluation, manual override and graceful fallback.

## 2. Questions likely in viva

### Operating Systems

**Q1. Is an exam attempt an OS process?**  
No. It is an application-level entity persisted in a relational database. We use lifecycle/checkpoint concepts as design analogies, and the OS scheduling lab separately simulates abstract jobs.

**Q2. What is FCFS?**  
First-Come, First-Served chooses the ready job with the earliest arrival and runs it to completion. It is non-preemptive in this simulator.

**Q3. What is Round Robin?**  
Each ready job receives at most a configured time quantum, then an unfinished job moves to the tail of the ready queue.

**Q4. Difference between waiting time and turnaround time?**  
Turnaround is completion time minus arrival time. Waiting time is turnaround minus CPU burst time under the simulator's zero-overhead model.

**Q5. What is response time?**  
First CPU start time minus arrival time.

**Q6. What is checkpointing in this application?**  
Persisting current answers/review status so the system can restore the latest acknowledged server state after refresh/interruption. It is not a literal OS memory checkpoint.

**Q7. What happens if a browser disconnects?**  
The persisted attempt remains `IN_PROGRESS`; its deadline continues. Reconnecting restores saved answers and computes remaining time from the persisted deadline. If overdue, it is finalized as `EXPIRED` on the next relevant access or sweep.

### DBMS

**Q8. Why PostgreSQL instead of only SQLite?**  
PostgreSQL offers the transaction, row-lock, constraints, and query-plan behavior needed by the project's concurrency and benchmark demonstrations. SQLite may be useful for trivial unit tests but does not replace PostgreSQL integration tests.

**Q9. What is normalization?**  
Organizing relational data to reduce avoidable redundancy and update anomalies. ExamOS separates users, question-bank data, exams, frozen exam snapshots, attempts and answers.

**Q10. Why freeze an exam snapshot?**  
If a question-bank option or correct answer changes later, an old attempt must still be graded against the exact question version the student saw. Snapshots preserve that historic definition.

**Q11. How do you prevent duplicate submissions?**  
A transaction locks the attempt row, checks its current status and authoritative deadline, computes the score and persists terminal state plus score atomically. Repeated requests return the existing result.

**Q12. What does ACID mean?**  
Atomicity, Consistency, Isolation and Durability—the properties we rely on for multi-step operations such as finalization.

**Q13. What is an index?**  
A data structure the database can use to find rows more efficiently for suitable predicates/orderings, at the cost of storage and write maintenance.

**Q14. Does an index always improve query speed?**  
No. A sequential scan can be cheaper for small tables or queries returning many rows. We show actual plans and timing instead of assuming an index wins.

**Q15. What is `EXPLAIN ANALYZE`?**  
It executes the statement and reports the plan plus actual runtime/row information. For this reason, only fixed, approved and safe benchmark statements are exposed in the lab.

### AI/ML

**Q16. Why TF-IDF?**  
It converts text into weighted lexical features suitable for a lightweight text-classification baseline. It is simple to train locally and inspect.

**Q17. Why Logistic Regression?**  
It is a practical baseline for sparse text features, has low runtime cost, and can return class probabilities for a configurable suggestion threshold.

**Q18. How do you evaluate the classifier?**  
Use a held-out stratified test set and report accuracy, per-class precision/recall/F1, macro F1 and a confusion matrix. Do not report a metric before actually running evaluation.

**Q19. What happens when the model is unavailable?**  
The UI falls back to manual topic selection. The question and exam workflows continue to work.

**Q20. Are topic performance insights ML?**  
Not in this version. They are deterministic statistics calculated from finalized responses and frozen question topics.

## 3. Evidence to prepare before the viva

- ER diagram from the final schema.
- Attempt lifecycle state diagram.
- Example output of each scheduling algorithm, including idle intervals.
- Actual PostgreSQL plans and timings for at least one lab scenario.
- A test showing duplicate finalization returns a stable result.
- A test showing the student payload does not reveal correct options before finalization.
- ML evaluation report generated from the real held-out dataset.
- Screenshots of a saved attempt, recovery, results, simulator and DB lab.
- `git log` or commits reflecting milestone progress.

## 4. Claims to avoid

Do not claim ExamOS is production-grade, immune to every network failure, kernel-level process scheduling, real-time expiry regardless of backend activity, faster indexed execution in every case, or a high-accuracy ML system unless evidence proves each claim. The project is stronger when its guarantees and limitations are stated precisely.

**Document Status:** Planning guide — validate against implemented behavior before presentation
