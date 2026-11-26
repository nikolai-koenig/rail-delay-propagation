# rail-delay-propagation

Modelling how delays propagate on the Great Western Main Line (Reading to Paddington) across GWR, Elizabeth line and freight services, using Darwin HSP and Network Rail TRUST data with graph neural networks.

> **Status:** early setup. The feed collector and reference-data tooling are in place. No results yet.

## Research questions

1. How far does an initial delay travel along the corridor, and how much is absorbed by timetable slack?
2. Does a freight train's presence in a section increase delay on following passenger services, compared with passenger-on-passenger interactions?
3. Do graph-based models predict propagation better than sequence models or gradient boosting?

## Repository layout

```
config/       corridor definition (corridor.yaml) and resolved location codes
data/         no data committed; see data/README.md
deploy/       systemd units for the unattended collectors
docs/         data sources and caveats, collector operation
src/rdp/      pipeline code (collector, reference data; models to follow)
tests/        unit tests (synthetic fixtures only)
```

## Getting started

Requires [uv](https://docs.astral.sh/uv/). Dependencies are pinned in `uv.lock`.

```bash
uv sync --locked          # make setup
uv run pytest             # make test
cp .env.example .env      # add credentials (never commit .env)
uv run rdp --help
```

On Windows without `make`, run the `uv run ...` commands from the [Makefile](Makefile) directly.

## Data

- **Darwin HSP**: passenger services, about a year of history, via the Rail Data Marketplace.
- **Network Rail TRUST**: all services including freight. There is no public archive, so we collect it ourselves from 2026-11.
- **SCHEDULE (CIF)** and **CORPUS**: the planned timetable and location codes.
- **Open-Meteo**: weather.
- **GOV.UK**: bank holidays.

Verified facts, assumptions and licences are in [docs/data-sources.md](docs/data-sources.md).

## Limitations (to be expanded)

- Single corridor; results may not transfer to other routes.
- HSP has known gaps, and absence from it does not mean a train was cancelled (see docs).
- Freight data only covers the period the collector has run.
- Heathrow Express has no intermediate calling points in the corridor, so Phase 1 treats it as context only.

## Data licences

Contains information of Network Rail Infrastructure Limited licensed under the Open Government Licence. This project is not affiliated with or endorsed by Network Rail, National Rail or the Rail Delivery Group.
