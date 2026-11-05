# Arkanine

Arkanine lets organisations that cannot use public LLMs build, own and continuously improve private AI systems from their internal knowledge, running entirely inside their own infrastructure.

## Language

**Private AI system**:
The set of models, knowledge index and evaluations that a customer runs inside their own boundary, built from their internal documents.
_Avoid_: Instance, tenant, bot, copilot

**Customer boundary**:
The infrastructure perimeter controlled by the customer, inside which all customer data and every Private AI system component must remain.
_Avoid_: Environment, perimeter, VPC

**Air-gapped**:
A Private AI system that works with no network path to the internet, at install, at run time and when updated.
_Avoid_: Offline, on-prem, private cloud

**Offline bundle**:
A signed package containing everything needed to install or update a Private AI system without any network access.
_Avoid_: Installer, release, update package

**Ownership**:
The customer decides where their Private AI system runs, what data enters it, and when it changes. Arkanine licenses the software and never holds the customer's data.
_Avoid_: Rental, hosted, managed

**Improvement loop**:
The process by which a Private AI system measurably gets better over time from the customer's own feedback and evaluations.
_Avoid_: Continuous learning, auto-training, evolution

**Collection**:
A named set of documents ingested into a Private AI system, and the unit to which access is granted.
_Avoid_: Library, corpus, index, folder

**Eval set**:
The approved questions, with expected answers and source citations, against which a configuration is scored.
_Avoid_: Test set, benchmark, golden set

**Candidate configuration**:
A proposed change to how a Private AI system retrieves and answers, not yet adopted.
_Avoid_: Experiment, variant, trial

**Promotion**:
Adopting a candidate configuration because it beat the current one on the eval set; it can be rolled back.
_Avoid_: Deploy, release, merge
