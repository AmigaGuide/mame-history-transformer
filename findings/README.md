# Findings Folder

This folder contains **outputs generated during data auditing and validation** for the TM470 *Lost in Translation* project.

These files are not part of the final structured JSON export, but serve as supporting evidence for:

- Identifying inconsistent or malformed metadata
- Justifying defensive parsing logic
- Supporting manual or automated post-processing
- Informing potential feedback to source maintainers (e.g. Gaming-History)

## Notable files

- `2025-07-31 - Unique Platforms Found (731).txt`  
  Raw list of 731 platform strings extracted from `history.xml`, each with a count of appearances.  
  Highlights the inconsistent naming conventions across systems, regions, editions, and platforms.  
  May inform future normalisation logic.

## Subfolders

- `/tools` - utilities and helper outputs created during auditing.  
  See the dedicated `README.md` inside `/findings/tools` for details.

## Notes

- Findings are versioned to maintain traceability and reproducibility across development stages.  
- They may be referenced in the final TM470 report or appendices where relevant.
