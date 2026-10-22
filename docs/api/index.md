# **API Reference**

The public interface, grouped by the code's own top-level split.

> **See also:** [Usage](../usage.md)

## Pages

| Group | Contents |
|-------|----------|
| [Reference](reference.md) | The public surface shipped on day one |

## Growing this section

This is a **directory, not a single page**, on purpose. An API reference grows once per shipped
unit, so a single `api.md` becomes the largest page in the repo; splitting it later is trivial
effort but **rots every published deep link** — and permanently, once versioned docs are live,
because `/<version>/api/#anchor` exists forever. The premium for starting as a directory is one
extra file and one nav level, paid once.

When you add pages:

- **Group by the codebase's own top-level split — never invent a parallel taxonomy**
  (e.g. one page per public module, mirroring the package's own split). A reader who knows the package can then guess the URL, and the docs cannot drift from
  a structure they mirror.
- **Depth follows count, not taste.** The real axis picks the sections; volume alone decides
  whether a section needs a second level.
- Prose shared by one group lives once on that group's page, not restated per item.
- **Register every new page in `mkdocs.yml` `nav:` in the same commit.** MkDocs builds an
  unregistered page anyway — it just vanishes from navigation, which is how a page silently goes
  missing (and what the `check_docs_sections.py` gate exists to catch).
