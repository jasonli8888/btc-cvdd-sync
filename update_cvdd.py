name: Daily CVDD Sync

on:
  schedule:
    - cron: '0 1 * * *'
  workflow_dispatch:

permissions:
  contents: write

jobs:
  build:
    runs-on: ubuntu-latest
    steps:
      - name: Checkout repo
        uses: actions/checkout@v4
        with:
          token: ${{ secrets.GITHUB_TOKEN }}

      - name: Set up Python
        uses: actions/setup-python@v5
        with:
          python-version: '3.11'

      - name: Install dependencies
        run: pip install requests pandas

      - name: Run CVDD sync script
        run: python update_cvdd.py

      - name: Commit and push real data files
        run: |
          git config user.name "github-actions[bot]"
          git config user.email "github-actions[bot]@://github.com"
          git add cvdd_indicator.pine cvdd_history.csv
          git diff --staged --quiet || git commit -m "Sync real daily on-chain CVDD data"
          git push
