# Denormalize scans (multiply by injection time)

:material-menu-open: **Raw data methods → Raw data filtering → Denormalize scans (multiply by injection time)**

!!! info "Documentation in progress"

    We are currently working on the documentation for this module. Until it is available, the
    parameter descriptions are shown as tooltips in the module's parameter dialog in mzmine.

## Description

Multiplies the intensities of a scan or mass list by the injection time to denormalize scans that were acquired on a trapped MS instrument. Intensities are usually divided by the injection (accumulation) time for normalization; this module reverts that. Scans without an injection time are left unchanged.
