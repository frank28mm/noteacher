# QA Replay Dataset

This directory contains test samples for validating the Autonomous Agent.

## Directory Structure

```
replay_data/
├── samples/          # JSON sample definitions
├── images/           # Test image files
└── README.md         # This file
```

## Adding Samples

Two supported approaches:

1) **Local images** (preferred when you can commit images):
   - Place test images in `images/`
   - Reference them via `input.local_images` in each sample JSON

2) **Embedded base64** (repo-friendly / text-only):
   - Put a `data:image/...;base64,...` string in `input.or_base64`
   - This allows the dataset to exist without committing binary files

Create the JSON in `samples/` following the format in `docs/qa_replay_dataset.md`.

## Recommended Sample Coverage

- 3-5 Simple arithmetic problems
- 3-5 Algebra problems
- 3-5 Geometry with diagrams
- 2-3 Poor OCR quality
- 2-3 Multi-question pages

Total: 10-20 samples

## Running Replay Tests

```bash
# Run all replay samples
python3 -m pytest homework_agent/tests/test_replay.py -v

# Run specific sample category
python3 -m pytest homework_agent/tests/test_replay.py -v
```

## Documentation

See [docs/qa_replay_dataset.md](../../../docs/qa_replay_dataset.md) for detailed structure.
