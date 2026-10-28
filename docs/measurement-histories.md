# Lesion-size measurements and timing

A reported question about “different mass measurements” retrieved discussion text and abstained despite dimensions being present. Vague wording, mismatched “mass”/“lesion” terms and equal context allocation to an unrelated selected document hid relevant observations.

`backend/measurements.py` recognizes explicit lesion-size requests without treating age/location, biopsy or body/calibration mass questions as dimensions. For these requests, retrieval supplements semantic hits with a bounded SQL search for dimension-bearing chunks. All session, selected-document, ready-state and embedding-identity predicates remain in place. Nonmeasurement chunks cannot consume the size-evidence budget.

Exact sentence windows keep an immediately preceding relative-time statement with an observation, within one physical page and the existing quote/context limits. Retrieval-only anchors associate mass/lesion terminology with dimensions. Requests for different/all measurements retain eligible distinct observations within the six-item answer budget rather than silently dropping a selected candidate. A narrower examination-specific question still uses selection.

Observed numeric fields are rendered directly from source spans, similarly to verified table cells: label, original dimensions/range, approximate qualifier and any explicit relative timepoint. The model selects evidence; it does not rewrite numeric size fields. Source cards retain exact quotations and physical-page links. Excision margins and scars are not treated as lesion dimensions; uptake values are not lesion lengths. An undated clinical observation remains a clinical assessment rather than receiving an invented date. Different methods/values do not establish growth.

The initial implementation recognizes cm/mm and spelled-out centimeter/millimeter values, scalar sizes, multiplication-style dimensions and ranges. It is a bounded text heuristic, not a universal timeline or measurement parser; complex layouts, other units and missing context remain limitations. A result reflects retrieved eligible observations, not proof of exhaustive extraction from arbitrarily large documents. No re-index or re-upload is required.

Tests vary dimensions and timepoints, preserve multiple physical-page quotations, include an unrelated selected document and an excluded competing document, and check exact dimension order, approximation/timing completeness and source scope. See the [verification summary](verification.md) for actual results.
