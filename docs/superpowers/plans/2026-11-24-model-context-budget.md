# Model Context Budget Implementation Plan

> **For agentic workers:** OpenSpec change `model-context-budget`. Execute tasks in `openspec/changes/model-context-budget/tasks.md`.

**Goal:** Replace fixed user/system prompt length caps with model `max_input_tokens` budget and compress-on-overflow.

**Architecture:** New `context_budget` helper; LLM params carry `max_input_tokens`; chat entry uses abuse ceiling; graph `fit_messages` before invoke.

**Tech Stack:** Python FastAPI, Vue admin + oa-agent-chat Composer.

## Global Constraints

- Default `max_input_tokens` = 100000; `chars ≈ tokens × 2`; reserve `max(max_tokens, 256)`
- Keep history_compress* knobs; no tiktoken; no new DB column
