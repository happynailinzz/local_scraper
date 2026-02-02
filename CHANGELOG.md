# Changelog

All notable changes to this project will be documented in this file.

## Unreleased

## v0.1.2 - 2026-02-02

- Add China relay endpoint `POST /relay/zcpt/fetch` with Bearer auth
- Add overseas support to fetch `zcpt.zgpmsm.com.cn` via `ZCPT_RELAY_BASE_URL` / `ZCPT_RELAY_TOKEN`
- Document relay configuration and env vars

## v0.1.1

- Fix GHCR build context

## v0.1.0

- Initial local scraper implementation
- WebUI with Basic Auth
- Task scheduler (cron/interval)
