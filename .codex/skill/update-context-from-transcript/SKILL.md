---
name: update-context-from-transcript
description: Use this skill when the user provides Bilibili transcript text, raw ASR output, or transcript-derived evidence and wants to update this repository's context.toml for a specific UP 主. This skill is for maintaining author-specific stock context, adding or refining stock-name corrections, distinguishing broad theme terms from single-stock aliases, and conservatively updating portfolio mappings from transcript evidence.
---

# Update Context From Transcript

Use this skill when the task is to update [context.toml](../../context.toml) from transcript evidence for this repository.

## Goal

Convert transcript evidence into conservative, maintainable `context.toml` updates for the summary-context injection flow.

## Valid Update Targets

Use the existing schema only:

1. `stock_pool`
2. `authors.portfolio.stocks`
3. `authors.alias_overrides`
4. `authors.theme_terms`

Pick the narrowest structure that matches the evidence.

## Decision Rules

### Prefer transcript over summary

If both raw transcript and LLM summary exist, treat the raw transcript as the primary evidence for:

- spoken abbreviations
- ASR mistakes
- blackwords / slang
- broad topic terms

Use the summary only as secondary confirmation.

### Be conservative with single-stock mappings

Only add a stock alias or misrecognition when the evidence strongly points to one specific stock.

Good candidates:

- obvious ASR typo with a clear target
- repeated near-homophone for the same stock
- full-name variants
- clearly author-specific shorthand

Do not map broad terms like:

- `CPU`
- `存储`
- `锂矿`
- sector names
- basket phrases

These belong in `authors.theme_terms`, not as stock aliases.

### Use `authors.theme_terms` for broad concepts

Put broad or multi-stock language into `authors.theme_terms`, for example:

- theme words
- basket phrases
- repeated combo blackwords
- ambiguous category words

`theme_terms` are topic hints only. They must not be treated as `alias -> single stock`.

### Do not invent unsupported holdings

Only add a stock into `authors.portfolio.stocks` when at least one is true:

- the user explicitly says it belongs in the UP 主 stock pool / holdings
- screenshot or direct evidence shows it in the portfolio
- repeated transcript evidence strongly supports that it is a standing tracked name and the user intent is to maintain the author's stock pool

A one-off mention in discussion is not enough.

### Keep the file maintainable

- Use formal stock names as `stock_pool` keys and `portfolio.stocks` values.
- If the stock code is uncertain, leave `code = ""`.
- Do not duplicate one idea across multiple schema fields unless the semantics are different.

## Update Workflow

1. Read the transcript carefully.
2. Extract candidate items:
   - formal stock names
   - likely ASR mistakes
   - likely spoken shorthand
   - broad theme words
3. Classify each item:
   - stock-level correction
   - author-specific alias override
   - theme term
   - insufficient evidence
4. Update `context.toml` conservatively.
5. Preserve existing user-curated entries unless new evidence directly contradicts them.
6. In the final response, state:
   - what was added
   - what was intentionally not added
   - which terms remain ambiguous

## Repository-Specific Guidance

This repository already supports:

- `stock_pool."<正式名称>"`
- `common_misrecognitions`
- `common_aliases`
- `[[authors]]`
- `authors.portfolio.stocks`
- `authors.alias_overrides`
- `authors.theme_terms`

Do not redesign the schema unless explicitly requested.

## Editing Rules

- Edit `context.toml` directly.
- Keep entries readable and grouped.
- Prefer omission over overfitting when evidence is weak.
- Do not convert broad topic words into single-stock aliases.

## Close-Out Expectations

When reporting back, summarize:

- confirmed alias/misrecognition additions
- newly added `theme_terms`
- terms rejected as too broad or too ambiguous
