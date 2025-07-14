# TM470 – Lost in Translation Parser

This repository contains code developed for the Open University TM470 project:

**"Adapting MAME and Gaming-History XML Metadata for ExoticA’s Lost in Translation."**

## Overview

This project automates the extraction and transformation of metadata from:

- **MAME XML** – Structured descriptions of arcade hardware, ROMs, and device relationships.
- **Gaming-History XML** – Semi-structured trivia including notes on arcade-to-home system conversions.

The output is a structured JSON representation of valid arcade machines, enriched with classification data. This will be used to populate infoboxes on ExoticA’s *Lost in Translation* wiki section.

## Core Components

| Module               | Purpose                                                                 |
|----------------------|-------------------------------------------------------------------------|
| `main.py`            | Pipeline controller and entry point                                     |
| `mame_parser.py`     | Parses MAME XML and applies clone-aware filtering using `.ini` metadata |
| `history_metadata.py`| Parses classification `.ini` files and maps metadata to each machine     |
| `encoding_utils.py`  | Detects and caches file encodings using `chardet`                        |
| `logger.py`          | Central logging configuration with support for multiple verbosity levels|
| `config.py`          | Defines global project constants, including logging level                |

> Note: `history_parser.py`, `transformer.py`, and `json_writer.py` are placeholders for upcoming stages.

## Features

- Clone-aware arcade filtering logic
- Classification-based validation using `.ini` files
- Detailed logging with toggleable verbosity (`INFO` or `DEBUG`)
- Performance timing for encoding detection and XML parsing
- Structured summaries of classification statistics

## Status

- ✔ Planning Complete  
- 🛠 Implementation In Progress  
- 🧪 Testing Planned
