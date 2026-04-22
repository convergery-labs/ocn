# auth-service

Part of the [ocn monorepo](../CLAUDE.md).

## Overview

`auth-service` is a shared service for authenticating API requests as they come in. Both - `news-retrieval` as well as `signal-detection` safeguard their APIs with an authentication layer that depends on this service.

## Jira Board
| Board | URL | Project Key |
|-------|-----|-------------|
| OCN Board | https://opengrowthventures.atlassian.net/jira/software/projects/CON/boards/34 | CON |

## Structure

See [STRUCTURE.md](STRUCTURE.md) for descriptions.

TODO: Add directory tree once service is implemented.

## Guidance

- Read only the docs relevant to your task
- Use the Jira board (project key `CON`) to track and reference cards

## Maintenance

- At the end of any session that restructures the codebase, update the Structure section above and the STRUCTURE.md file
- Do not modify the Jira Board, Guidance, or Maintenance sections unless explicitly asked
