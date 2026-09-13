# Third-party notices

## AgentForge

Contexer contains focused adaptations of architectural patterns and selected
implementation concepts from [AgentForge](https://github.com/MohitGoyal09/AgentForge),
commit `3f513b36b8cd5f7c4c3303506dcbdec949f9e23c`.

Copyright (c) 2026 Mohit Goyal

Licensed under the MIT License:

```text
MIT License

Copyright (c) 2026 Mohit Goyal

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
```

## Dependency boundary

No AgentForge package or AgentForge-only dependency is bundled or added as a
runtime dependency by this integration. AgentForge declares separate
dependencies including `anthropic`, `httpx`, `click`, `platformdirs`,
`tiktoken`, `ddgs`, and `fastmcp`; those packages and their licences do not
enter Contexer's distribution through this work because the related AgentForge
features are not imported.

Contexer continues to distribute only the dependencies declared in its own
`pyproject.toml`. Their licences remain separate obligations when Contexer is
distributed. Before a release, generate an SBOM/licence report from the locked
environment so the exact resolved versions and licence texts are included.
