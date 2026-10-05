# Import molecular networks/feature networks (csv/tsv)

:material-menu-open: **Feature list methods → Export feature list → Import molecular networks/feature networks (csv/tsv)**

!!! info "Documentation in progress"

    We are currently working on the documentation for this module. Until it is available, the
    parameter descriptions are shown as tooltips in the module's parameter dialog in mzmine.

## Description

Imports molecular networks or other feature networks into feature lists, which can then be visualized with the interactive network visualizer. Input files are comma-separated (csv) or tab-separated (tsv) files with the columns `ID1,ID2,EdgeType,EdgeAnnotation,EdgeScore`. `ID1` and `ID2` must correspond to feature list row IDs in the selected feature lists. `EdgeType` and `EdgeAnnotation` are strings that define the method used and the annotation of the edge. `EdgeScore` is a floating point number.
