# Agent instructions: articles

- Articles about the repository for readers outside it, each dated in its name and never updated: what it says is true at its date.
- Each is one self-contained HTML file, its data and scripts embedded: its CSS starts with a copy of `articles/theme.css`, the base theme of the articles, never linked, and adds what that article needs.
- `articles/index.html` lists them, newest first, and gets an entry with each new one.
- `.github/workflows/pages.yml` publishes the folder on GitHub Pages at each push to master that changes it.
- The reference docs never point to them.
