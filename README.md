# TM470 – Lost in Translation Parser

This repository contains code developed for the Open University TM470 project:

**"Adapting MAME and Gaming-History XML Metadata for ExoticA’s Lost in Translation."**

## Overview

This project automates the extraction, classification, and transformation of metadata from:

- **MAME XML** – Highly structured data describing arcade machines, ROMs, CPUs, and clone relationships.
- **Gaming-History XML** – Semi-structured trivia including arcade-to-home conversion details stored under headings like `PORTS`.

The goal is to generate a structured JSON dataset suitable for populating ExoticA’s *Lost in Translation* wiki infoboxes, enabling easier maintenance and expansion.

## Core Components

| Module                | Purpose                                                                 |
|-----------------------|-------------------------------------------------------------------------|
| `main.py`             | Entry point; coordinates encoding detection and conditional parsing     |
| `mame_parser.py`      | Extracts arcade machine data and applies clone filtering and `.ini` rules |
| `history_metadata.py` | Parses `.ini` metadata to classify and validate machines                |
| `history_parser.py`   | Extracts and normalises `PORTS` section from Gaming-History XML         |
| `encoding_utils.py`   | Detects and caches file encodings using `chardet`                       |
| `logger.py`           | Sets up consistent logging across modules                               |
| `config.py`           | Defines global constants including logging verbosity                    |

## Features

- Streamed XML parsing for reduced memory usage
- Classification-aware filtering using `.ini` metadata
- Detection and reporting of formatting anomalies (e.g. unmatched quotes or brackets)
- Structured output as UTF-8 JSON with readable formatting
- Defensive coding and fallback logic for edge cases
- Version-aware reprocessing logic using `encodings.json`

## Outputs

- `output/gh_entries.json` – Parsed Gaming-History data for valid arcade systems
- `data/history_parsing_summary.json` – Summary of headings, categories, anomalies, and residue
- `output/mame_summary.json` – Classification summary for MAME entries
- Logs stored in the `logs/` directory

## Project Status

- **Planning** – Complete  
- **MAME XML Parsing** – In progress
- **INI Classification Logic** – Implemented  
- **Gaming-History Parsing** – In progress  
- **Anomaly Detection** – Implemented (quotes, brackets, unexpected categories)  
- **Final Integration** – Ongoing  
- **Wiki Transformation** – To be developed

---

