# Content Factory Rewrite Design

Date: 2026-06-03

## 1. Decision

This project will be rewritten around a new **Content Factory** architecture. The rewrite is not an incremental extension of the current `pixelle_video` pipeline. Existing code may be used as reference or selectively migrated, but the new project structure, data flow, state model, and user workflow will be designed around end-to-end content production and publish-package execution.

The system goal is:

```text
topic or direction input
  -> reference content collection
  -> popular content analysis
  -> creation-method breakdown
  -> original creative brief
  -> copy / image prompt / video prompt / storyboard generation
  -> asset generation or manual asset replacement
  -> human review
  -> publish package creation
  -> publish queue
  -> CH9329 phone draft upload
  -> status logging and error recovery
```

The computer performs topic analysis, content generation, asset generation, review, packaging, queueing, and logging. CH9329 is used only for the final phone-side upload execution.

## 2. Architecture

The new system is split into two primary domains.

### 2.1 Content Factory

Responsible for:

- topic tasks;
- source/reference collection;
- source normalization;
- analysis reports;
- creative briefs;
- generated copy, prompts, and storyboards;
- asset tasks and generated/manual assets;
- compliance and originality checks;
- human review;
- publish package creation.

### 2.2 Publish Executor

Responsible for:

- publish queue;
- platform publish modes;
- device profiles;
- coordinate profiles;
- CH9329 control;
- mobile upload flow execution;
- screenshots and step logs;
- failure pause and retry;
- manual intervention;
- resuming from a failed step.

The two domains communicate through one artifact:

```text
PublishPackage
```

The content-generation system produces a publish package. The publish executor consumes that package. This keeps content generation independent from phone-control logic.

## 3. First Implementation Scope

The first implementation will cover:

- project skeleton;
- FastAPI backend;
- SQLite + SQLAlchemy persistence;
- task state machine;
- topic task creation;
- manual source import;
- public browser-assisted collection skeleton;
- cookie-assisted collection configuration skeleton;
- source digest generation;
- analysis report generation;
- original creative brief generation;
- image-text copy generation;
- short-video script, storyboard, and prompt generation;
- originality and platform-risk checks;
- mock asset provider;
- manual upload provider;
- publish package generation;
- review records;
- basic publish queue;
- device profiles;
- coordinate YAML profiles;
- CH9329 executor skeleton;
- Xiaohongshu draft-upload flow recording / dry-run foundation;
- logs and failure-state records.

The first implementation will not require:

- fully automated publishing to every platform;
- automatically clicking the final publish button;
- high-volume cookie collection;
- CAPTCHA bypass or risk-control evasion;
- high-frequency multi-account posting;
- mature multi-device scheduling;
- deep real video-generation API integration;
- complex visual recognition;
- real official platform API publishing;
- polished production-grade frontend UI.

## 4. Recommended Technology Stack

Backend:

- Python;
- FastAPI;
- SQLAlchemy;
- SQLite;
- Pydantic.

Frontend:

- local web console;
- simple server-rendered pages or lightweight frontend for the first version;
- React/Vue can be added later if needed.

Workers:

- built-in asynchronous task runner for the first version;
- no first-version dependency on Celery, Redis, or PostgreSQL.

Storage:

- SQLite for task state;
- `runtime/` for sources, assets, packages, logs, screenshots, and coordinate profiles.

Automation:

- CH9329 serial control;
- YAML action flows;
- coordinate recording and replay;
- screenshots and step logs.

AI and providers:

- abstract LLM provider;
- abstract asset provider;
- mock and manual providers first;
- real image/video providers added through provider adapters.

## 5. Proposed Project Structure

```text
content_factory/
  app/
    main.py
    api/
      routes_topics.py
      routes_sources.py
      routes_analysis.py
      routes_generation.py
      routes_assets.py
      routes_review.py
      routes_publish.py
      routes_devices.py
    web/
      pages/
      components/

  core/
    config.py
    database.py
    security.py
    logging.py

  domain/
    topics/
      models.py
      service.py
    sources/
      models.py
      service.py
    analysis/
      models.py
      service.py
      prompts.py
    generation/
      models.py
      service.py
      prompts.py
    assets/
      models.py
      service.py
      providers/
        base.py
        image_provider.py
        video_provider.py
        tts_provider.py
    review/
      models.py
      service.py
    publish/
      models.py
      service.py
      package_builder.py
    devices/
      models.py
      service.py
    automation/
      ch9329/
        controller.py
        recorder.py
        executor.py
        calibration.py
      flows/
        xhs_upload.yaml
        douyin_upload.yaml
        generic_upload.yaml

  workers/
    task_runner.py
    content_worker.py
    asset_worker.py
    publish_worker.py

  storage/
    repositories.py
    migrations/
    runtime/

  integrations/
    llm/
      base.py
      anthropic_provider.py
      openai_compatible_provider.py
    browser/
      collector.py
    platforms/
      xhs.py
      douyin.py
      generic.py

  tests/
```

Directory responsibilities:

- `domain/` contains business modules;
- `integrations/` contains third-party interfaces;
- `domain/automation/` contains CH9329 and coordinate-flow logic;
- `workers/` runs asynchronous jobs;
- `app/api/` exposes HTTP endpoints and does not contain complex business logic;
- `storage/` owns persistence and runtime files.

## 6. Core Data Objects

### 6.1 TopicTask

Represents one content-production task.

Fields:

- `id`;
- `title`;
- `direction`;
- `target_platforms`;
- `content_type`;
- `status`;
- `created_at`;
- `updated_at`.

### 6.2 SourceItem

Represents one reference item collected from manual input, browser-assisted public pages, cookie-assisted pages, screenshots, videos, CSV, or JSON.

Fields:

- `id`;
- `topic_task_id`;
- `source_type`;
- `platform`;
- `url`;
- `title`;
- `text`;
- `images`;
- `videos`;
- `author_name`;
- `publish_time`;
- `like_count`;
- `comment_count`;
- `collect_count`;
- `raw_snapshot_path`;
- `risk_level`;
- `created_at`.

### 6.3 SourceDigest

A normalized digest of a source item for analysis.

Fields:

- `source_item_id`;
- `title`;
- `main_text`;
- `visible_comments`;
- `image_descriptions`;
- `video_descriptions`;
- `engagement_summary`;
- `possible_audience`;
- `possible_intent`;
- `notable_patterns`;
- `copied_text_risk`.

### 6.4 AnalysisReport

A method-level breakdown of reference content. This artifact must not provide copied source content as output.

Fields:

- `id`;
- `topic_task_id`;
- `source_item_ids`;
- `title_patterns`;
- `hook_patterns`;
- `content_rhythm`;
- `visual_elements`;
- `cover_patterns`;
- `comment_demands`;
- `reusable_angles`;
- `forbidden_copy_points`;
- `originality_notes`;
- `created_at`.

### 6.5 CreativeBrief

The original creative plan generated from an analysis report.

Fields:

- `id`;
- `topic_task_id`;
- `analysis_report_id`;
- `target_audience`;
- `unique_angle`;
- `key_message`;
- `title_candidates`;
- `outline`;
- `visual_direction`;
- `tone`;
- `platform_strategy`;
- `risk_warnings`;
- `approved`;
- `created_at`.

### 6.6 GeneratedContent

The generated title, body copy, hashtags, prompts, and storyboard.

Fields:

- `id`;
- `creative_brief_id`;
- `platform`;
- `content_type`;
- `title`;
- `body`;
- `cover_text`;
- `hashtags`;
- `image_prompts`;
- `video_prompts`;
- `storyboard`;
- `publish_time_suggestion`;
- `compliance_notes`;
- `created_at`.

### 6.7 AssetTask and AssetItem

`AssetTask` represents a request to create or provide one asset. `AssetItem` represents the actual image, video, cover, audio, or manually uploaded file.

Asset task statuses:

- `pending`;
- `running`;
- `succeeded`;
- `failed`;
- `cancelled`;
- `needs_manual_upload`.

Asset item fields:

- `id`;
- `generated_content_id`;
- `asset_type`;
- `provider`;
- `prompt`;
- `local_path`;
- `remote_url`;
- `status`;
- `checksum`;
- `error_message`;
- `created_at`.

### 6.8 ComplianceCheck

A lightweight originality and risk check.

Fields:

- `originality_score`;
- `copied_phrase_warnings`;
- `platform_risk_warnings`;
- `sensitive_word_warnings`;
- `recommended_fixes`.

Low-scoring content cannot become a publish package until it is edited or approved after manual review.

### 6.9 ReviewRecord

Tracks human review.

Statuses:

- `pending`;
- `approved`;
- `rejected`;
- `needs_edit`.

Fields:

- `id`;
- `generated_content_id`;
- `reviewer`;
- `status`;
- `comments`;
- `approved_at`;
- `created_at`.

### 6.10 PublishPackage

The handoff artifact from Content Factory to Publish Executor.

Fields:

- `id`;
- `generated_content_id`;
- `platform`;
- `account_id`;
- `title`;
- `body`;
- `hashtags`;
- `cover_asset_id`;
- `media_asset_ids`;
- `scheduled_time`;
- `publish_mode`;
- `status`;
- `created_at`.

Publish modes:

- `manual_export`;
- `phone_ch9329_draft`;
- `phone_ch9329_publish`;
- `browser_assist`;
- `official_api`.

The first version prioritizes `manual_export` and `phone_ch9329_draft`.

### 6.11 PublishJob and PublishJobLog

`PublishJob` represents one actual upload execution.

Fields:

- `id`;
- `publish_package_id`;
- `platform`;
- `account_id`;
- `device_id`;
- `status`;
- `retry_count`;
- `max_retries`;
- `error_message`;
- `started_at`;
- `finished_at`.

`PublishJobLog` records each executor step.

Fields:

- `job_id`;
- `device_id`;
- `step_index`;
- `step_name`;
- `action_type`;
- `status`;
- `started_at`;
- `finished_at`;
- `screenshot_path`;
- `error_message`.

### 6.12 DeviceProfile and CoordinateProfile

`DeviceProfile` describes one phone and CH9329 channel.

Fields:

- `id`;
- `name`;
- `platform`;
- `account_name`;
- `ch9329_port`;
- `screen_width`;
- `screen_height`;
- `app_version`;
- `os_version`;
- `coordinate_profile_id`;
- `status`;
- `created_at`.

`CoordinateProfile` stores one reusable upload flow.

Fields:

- `id`;
- `device_id`;
- `platform`;
- `app_version`;
- `screen_width`;
- `screen_height`;
- `flow_name`;
- `steps`;
- `created_at`.

## 7. Task State Machine

Main successful flow:

```text
created
  -> collecting_sources
  -> sources_ready
  -> analyzing
  -> analysis_ready
  -> brief_generating
  -> brief_ready
  -> content_generating
  -> content_ready
  -> assets_generating
  -> assets_ready
  -> review_pending
  -> approved
  -> publish_packaged
  -> queued_for_publish
  -> publishing
  -> published
```

Failure states:

```text
failed_collecting
failed_analysis
failed_generation
failed_asset_generation
failed_review
failed_publish
```

Manual-intervention states:

```text
needs_manual_input
needs_recalibration
needs_retry
paused
cancelled
```

The first version will persist states in SQLite. Runtime files are stored under `runtime/`.

## 8. Source Collection Design

All source collection methods produce `SourceItem` records.

### 8.1 Manual Import

Supported inputs:

- pasted title;
- pasted body text;
- pasted comment text;
- pasted links;
- uploaded images;
- uploaded videos;
- CSV import;
- JSON import.

Manual import is the default and most stable first-version collection method.

### 8.2 Browser-Assisted Public Collection

The system may open public pages, collect visible content, save screenshots, and ask the user to confirm extracted data. It does not bypass login, CAPTCHA, or platform risk controls. If extraction fails, the task enters `needs_manual_input`.

### 8.3 Cookie-Assisted Collection

Cookie-assisted collection is an advanced mode. It is not enabled by default.

Constraints:

- user must configure it explicitly;
- each platform has a separate enable switch;
- execution is low-frequency;
- failed collection stops instead of repeatedly retrying;
- no CAPTCHA bypass;
- no risk-control evasion;
- collection logs are saved;
- risk warnings are shown before use.

## 9. Content Analysis and Original Generation

The content production path is:

```text
TopicTask
  -> SourceItem[]
  -> SourceDigest[]
  -> AnalysisReport
  -> CreativeBrief
  -> GeneratedContent
```

The `AnalysisReport` extracts methods, not reusable copied content. It analyzes:

- title structures;
- high-interaction patterns;
- opening hooks;
- content rhythm;
- visual composition;
- cover style;
- comment-section needs;
- reusable but non-copied creation angles;
- forbidden copy points.

The `CreativeBrief` is the originality boundary. Final copy, prompts, and storyboards are generated from the creative brief rather than direct source rewrites.

First-version generated outputs include:

- new topic directions;
- original titles;
- original body copy;
- cover copy;
- image prompts;
- video prompts;
- storyboard;
- publish time suggestions;
- tags and topic suggestions.

Batch generation is allowed but bounded:

- default 3-5 candidate contents per topic;
- maximum 20 topics per batch;
- maximum 10 publish packages queued at one time in the first version.

## 10. Asset Provider Design

The asset layer uses an `AssetProvider` interface.

Provider interface:

```text
name
supported_types
validate_config()
generate(request) -> AssetResult
get_status(task_id)
download(result) -> local_path
```

Request shape:

```text
asset_type
prompt
negative_prompt
aspect_ratio
duration
style
reference_assets
output_dir
provider_config
```

Result shape:

```text
provider
provider_task_id
status
remote_url
local_path
metadata
error_message
```

First-version providers:

- `mock_provider` for end-to-end testing without external APIs;
- `manual_upload_provider` for user-provided assets;
- one minimal real image provider if configuration is available;
- video provider skeleton, falling back to manual upload if not configured.

## 11. Runtime File Layout

Recommended runtime layout:

```text
runtime/
  db/
    content_factory.sqlite
  tasks/
    {topic_task_id}/
      sources/
      analysis_report.json
      creative_brief.json
      generated_content/
      assets/
        images/
        videos/
        covers/
      publish_package/
      logs/
  screenshots/
  coordinate_profiles/
```

Publish package layout:

```text
runtime/tasks/{topic_task_id}/publish_package/{package_id}/
  package.json
  title.txt
  body.txt
  hashtags.txt
  cover.png
  media/
    01.png
    02.png
    03.png
```

## 12. Review Center

Human review is mandatory before creating a publish package.

The review center shows:

- topic task;
- source summaries;
- analysis report;
- creative brief;
- generated copy;
- images/videos;
- originality check;
- platform risk warnings;
- publish package preview.

Review actions:

- approve;
- reject;
- needs edit;
- regenerate;
- manual asset replacement.

## 13. CH9329 Phone Upload Design

CH9329 is a physical publish executor. It consumes approved publish packages and uploads them to mobile apps.

First-version default mode:

```text
phone_ch9329_draft
```

The system saves content to a platform draft instead of clicking final publish by default.

### 13.1 Standard Upload Path

For Xiaohongshu image-text drafts:

```text
1. confirm phone is unlocked
2. open Xiaohongshu app
3. enter publish entry
4. select images/videos
5. input title
6. input body
7. input tags
8. set cover if needed
9. check preview
10. save draft
11. record result
```

### 13.2 Coordinate Recording

Coordinate flows are recorded and saved as YAML.

Example:

```yaml
platform: xhs
flow_name: create_image_text_draft
screen:
  width: 1080
  height: 2400
app_version: "8.x"
steps:
  - type: tap
    x: 540
    y: 2250
    note: "tap publish button"
  - type: wait
    seconds: 1.5
  - type: input_text
    field: title
    source: publish_package.title
```

Coordinates store both absolute values and ratios when possible:

```text
x_ratio = x / screen_width
y_ratio = y / screen_height
```

### 13.3 Device Stability Requirements

Each device profile records:

- resolution;
- display scaling;
- font size;
- system language;
- input method;
- app version;
- screen orientation;
- notification/bar assumptions;
- battery and sleep settings.

Recommended device settings:

- portrait mode;
- fixed resolution;
- fixed font size;
- auto-rotation off;
- floating windows off;
- auto-brightness off;
- lock timeout disabled or extended;
- fixed input method;
- fixed app version.

### 13.4 Execution Safeguards

Critical steps can include:

- screenshots;
- screenshot checkpoints;
- manual pause points;
- dry-run mode;
- retry current step;
- continue from selected step.

Final publish is not automatic in the first version. If direct publish mode is later enabled, the final publish action must have a manual confirmation gate.

## 14. Web Console

The first version uses a local web console with these pages:

1. Dashboard;
2. Topics;
3. Sources;
4. Factory;
5. Review;
6. Publish Queue;
7. Devices.

Dashboard shows:

- generated content count;
- pending reviews;
- pending publish jobs;
- running publish jobs;
- failed jobs;
- online devices;
- manual-intervention items.

The main user flow is:

```text
create topic
  -> import references
  -> one-click analysis/generation
  -> review
  -> generate publish package
  -> queue draft upload
  -> dry-run or CH9329 upload
```

## 15. Platform Adapter Design

Each platform is represented by a `PlatformAdapter`.

Adapter responsibilities:

- title length;
- body length;
- hashtag rules;
- media count limits;
- supported content types;
- supported publish modes;
- default review rules;
- default upload flow.

First-version support:

- Xiaohongshu image-text publish package and CH9329 draft upload skeleton;
- generic short-video publish package export;
- generic manual export for other platforms.

## 16. Error Handling

Every error records:

- `error_code`;
- `error_message`;
- `stage`;
- `retryable`;
- `suggested_action`;
- `created_at`;
- optional `screenshot_path`;
- optional `raw_response_path`.

Error categories:

1. automatically retryable errors;
2. provider-switch errors;
3. human-judgment errors;
4. device/coordinate errors.

Retry rules:

- content generation retries up to 2 times and stores raw model output;
- asset generation retries up to 2 times, supports provider switching, and supports manual replacement;
- publish execution does not blindly replay a full job. It can retry a step, resume from a step, or pause for manual confirmation.

## 17. Logging

Three logs are required:

### 17.1 Task Log

Records the lifecycle of a topic task.

### 17.2 Provider Log

Records external provider calls without storing API keys or cookie secrets in plaintext.

### 17.3 Publish Execution Log

Records each CH9329 action step, coordinates, screenshots, status, and errors.

## 18. Security and Compliance Boundaries

The system must follow these boundaries:

- only user-owned or authorized accounts and devices;
- public/allowed data and manual import are preferred;
- cookie mode is advanced and not default;
- no CAPTCHA bypass;
- no platform risk-control evasion;
- no fake engagement or spam automation;
- no direct copying of source copy;
- no direct replication of source media;
- human review before publish package creation;
- draft upload by default;
- bounded generation and publish rates.

## 19. Testing Strategy

### 19.1 Unit Tests

Cover:

- data models;
- state transitions;
- provider interfaces;
- publish package builder;
- platform validation;
- coordinate YAML parsing;
- error categorization.

### 19.2 Integration Tests

Use mock LLM, mock asset provider, and mock CH9329 executor to test:

```text
topic -> source -> analysis -> brief -> content -> assets -> review -> publish package
```

### 19.3 Device Tests

Real CH9329/phone tests are local/manual tests, not ordinary CI tests.

Cover:

- serial connection;
- tap;
- keyboard input;
- shortcuts;
- screenshot save;
- dry-run;
- resume from failed step;
- device lock;
- multi-device queue skeleton.

## 20. Acceptance Criteria

### 20.1 Content Production

- user can create a topic task;
- user can import reference content;
- system can generate an analysis report;
- system can generate an original creative brief;
- system can generate image-text copy;
- system can generate short-video scripts, storyboards, and prompts;
- system can generate originality and platform-risk checks.

### 20.2 Assets and Review

- system can create asset tasks;
- mock provider can complete asset tasks;
- manual provider can replace assets;
- user can review generated content;
- user can approve, reject, request edits, or regenerate;
- approved content can become a publish package.

### 20.3 Publishing and Devices

- user can create a device profile;
- user can save coordinate YAML;
- user can create a publish job;
- CH9329 executor supports dry-run;
- executor records step logs;
- failures pause execution;
- execution can resume from a selected step;
- Xiaohongshu draft-upload flow has a recordable/testable skeleton.

### 20.4 Stability

- states are persisted in SQLite;
- runtime files are stored under `runtime/`;
- errors have codes and suggested actions;
- the full chain can run with mock providers and without real external APIs.

## 21. Implementation Phases

### Phase 0: Skeleton and Infrastructure

- package structure;
- FastAPI app;
- SQLite and SQLAlchemy;
- config;
- logging;
- runtime directories;
- basic web console shell;
- task state machine.

### Phase 1: Content Production Loop

- manual source import;
- source digest;
- analysis report;
- creative brief;
- generated content;
- originality and risk checks;
- basic review page.

### Phase 2: Assets and Publish Packages

- asset provider interface;
- mock provider;
- manual upload provider;
- minimal image provider adapter if configured;
- publish package builder;
- publish package export.

### Phase 3: CH9329 Draft Upload Skeleton

- device profiles;
- coordinate profiles;
- coordinate YAML;
- CH9329 controller wrapper;
- recorder;
- action executor;
- single-device Xiaohongshu image-text draft flow;
- screenshots;
- step logs;
- failure pause;
- resume from step.

### Phase 4: Batch and Multi-Device

- CSV/JSON topic batch import;
- batch generation;
- publish queue;
- device scheduler;
- device locks;
- health checks;
- retry controls.

### Phase 5: Multi-Platform Expansion

- platform adapters;
- generic short-video publish package;
- additional coordinate flows;
- browser-assisted publish;
- official API publish adapters when stable and available.

## 22. Final Recommendation

Rewrite the project as a local web-based **Content Factory** system. The first version should prove the full chain from topic input to publish package generation, then provide a CH9329 draft-upload skeleton for Xiaohongshu. The defaults should be conservative: human review, draft upload, mock/manual providers, low-frequency execution, and explicit failure recovery.
