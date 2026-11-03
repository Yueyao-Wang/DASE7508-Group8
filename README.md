# DASE7508-Group5-Project

## Project Purpose

This project is for the DASE7508 course (Security of Intelligent Systems).

We investigate whether an LLM agent can recover after a compromised third-party tool poisons its long-term memory. Our prototype simulates a note-taking agent, demonstrates how malicious tool output can trigger persistent unauthorized actions, and evaluates whether rolling back to a trusted checkpoint restores safe behavior while preserving legitimate task performance.

## Project Overview

The system contains a lightweight Python agent, a mock third-party note tool, JSON-based long-term memory and notes, audit logs, a checkpoint module, and a rollback recovery script.

In the normal scenario, a request to modify Chinese notes changes only those notes. In the attack scenario, a compromised tool injects a false authorization rule into memory, causing the agent to modify Math notes without authorization. The recovery mechanism restores the memory and note states from a trusted pre-attack checkpoint; audit logs are retained as evidence and are not rolled back.

## Threat Model

- The attacker controls only the text returned by one third-party tool.
- Tool output is untrusted and writing it to long-term memory is the persistence boundary.
- The attacker cannot directly modify system prompts, user requests, notes, memory files, logs, or checkpoints.
- Attack detection is assumed to occur after the poisoning event and is outside this project's scope.
- Checkpoints and the rollback mechanism are trusted.

## Experimental Conditions

We compare the following conditions:

| Condition | Description |
| --- | --- |
| `C0` Clean baseline | No attack and no recovery. |
| `C1` Attack / no recovery | The attack succeeds and poisoned memory remains. |
| `C2` Attack / rollback recovery | The attack succeeds, then the system rolls back to a trusted checkpoint. |

The evaluation reports the Unauthorized Modification Rate (UMR), Task Success Rate (TSR), Residual Contamination Rate (RCR), and Legitimate Progress Loss (LPL). Recovery is successful when later unauthorized Math-note changes no longer occur and normal-task success is at least 90% of the clean baseline.

## Prerequisites

Before you begin, ensure you have the following installed:

- Python 3.9+
- Git
- An optional LLM API key or a local Ollama model (the project can use synthetic responses for the core experiments)

## Setup Instructions

1. Clone the repository:

   ```bash
   git clone https://github.com/Yueyao-Wang/DASE7508-Group5.git
   ```

2. Enter the project directory:

   ```bash
   cd DASE7508-Group5
   ```

3. Create and activate a virtual environment:

   ```bash
   python -m venv .venv
   ```

   Windows PowerShell:

   ```powershell
   .\.venv\Scripts\Activate.ps1
   ```

   macOS/Linux:

   ```bash
   source .venv/bin/activate
   ```

4. Install dependencies (once `requirements.txt` is available):

   ```bash
   pip install -r requirements.txt
   ```

## Planned Workflow

1. Run a clean task and save a trusted checkpoint of the memory and note states.
2. Enable the malicious tool response and observe memory poisoning and unauthorized changes.
3. Detect the attack and restore the trusted checkpoint with the rollback script.
4. Replay normal tasks and compare the recovered system with the clean baseline.

## Expected Repository Structure

```text
.
├── src/                 # Agent, mock tool, memory, checkpoint, and rollback logic
├── data/                # Synthetic Chinese and Math notes
├── checkpoints/         # Trusted snapshots of memory and notes
├── logs/                # Audit logs retained across rollback
├── experiments/         # Experiment configurations and evaluation scripts
├── tests/               # Unit and integration tests
├── requirements.txt
└── README.md
```

## Team

- ZHANG Ruohan
- WANG Yueyao
- MENG Qingwei
- ZHONG Yilin
- CUI Haoming

## License

This repository is intended for academic use in DASE7508.


This line is for testing the review workflow.
