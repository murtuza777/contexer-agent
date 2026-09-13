---
name: technical-seo
description: Guidelines for implementing SEO-ready metadata, Open Graph cards, Twitter cards, robots.ts, sitemap.ts, and semantic search structure for developer platforms.
---

# Technical SEO Guidelines

Use this skill when configuring metadata, search indexing, social previews, and discoverability for the Contexer website.

## Implementation Details

1. **Metadata Definition in App Router**:
   - Define export `metadata: Metadata` in `app/layout.tsx` or `app/page.tsx`:
     - `title`: Descriptive, concise (`Contexer | Autonomous Engineering Agent`).
     - `description`: Accurate technical summary ("Autonomous engineering agent that plans, builds, tests, observes, and fixes your code.").
     - `metadataBase`: Canonical origin URL (e.g. `https://contexer.dev`).
     - `openGraph`: Type `website`, locale `en_US`, url, title, description, siteName.
     - `twitter`: Card `summary_large_image`, title, description.
     - `keywords`: Developer-focused indexing tags.

2. **Indexation Rules (`robots.ts`)**:
   - Provide standard Next.js App Router `robots.ts` returning user agents, allow paths, and sitemap URL reference.

3. **Sitemap Generation (`sitemap.ts`)**:
   - Provide standard Next.js App Router `sitemap.ts` exporting default function returning array of route URLs with `lastModified`, `changeFrequency`, and `priority`.

4. **Semantic HTML**:
   - Single `<h1>` per page for primary heading.
   - Structured `<h2>` and `<h3>` tags for subsections.
   - Semantic `<section>` blocks with clear headings for assistive technologies and search crawlers.
