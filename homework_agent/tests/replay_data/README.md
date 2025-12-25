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

1. Place test images in `images/` directory
2. Create corresponding JSON in `samples/` following format in `docs/qa_replay_dataset.md`

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
python -m pytest homework_agent/tests/test_replay.py -v

# Run specific sample category
python -m pytest homework_agent/tests/test_replay.py::test_simple_arithmetic -v
```

## Documentation

See [docs/qa_replay_dataset.md](../../../docs/qa_replay_dataset.md) for detailed structure.
