# findings/

This folder contains outputs generated during data auditing and validation phases of the TM470 project.

These files represent insights, anomalies, and extracted metadata from the Gaming-History XML and MAME XML datasets. They are not part of the final structured JSON output, but serve as supporting evidence for:

- Identifying inconsistent or malformed metadata
- Justifying defensive parsing logic
- Supporting manual or automated post-processing
- Informing potential feedback to source maintainers (e.g. Gaming-History)

## Notable Files

- `2025-07-31 - Unique Platforms Found (731).txt`:  
  Raw list of 731 platform strings extracted from `history.xml`, each with a count of appearances.  
  This file highlights the inconsistent naming conventions across systems, regions, editions, and platforms. It may inform future normalisation logic.

## Notes

These findings are versioned to maintain traceability and reproducibility across development stages. Where necessary, they may be referenced in the final TM470 report or appendices.
