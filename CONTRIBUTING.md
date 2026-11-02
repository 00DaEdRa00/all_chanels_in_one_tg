# Contributing to All Channels in One TG

Thank you for your interest in contributing to this project!

## Getting Started

1. Fork and clone the repository:
   ```bash
   git clone https://github.com/00DaEdRa00/all_chanels_in_one_tg.git
   cd all_chanels_in_one_tg
   ```

2. Create a virtual environment and install dependencies:
   ```bash
   python -m venv venv
   source venv/bin/activate  # On Windows: venv\Scripts\activate
   pip install -r requirements.txt
   ```

3. Copy configuration:
   ```bash
   cp .env.example .env
   ```

## Development Guidelines

- Run tests before pushing:
  ```bash
  python -m unittest discover tests
  ```
- Follow PEP 8 guidelines.
- Use conventional commits (`feat: ...`, `fix: ...`, `docs: ...`).
