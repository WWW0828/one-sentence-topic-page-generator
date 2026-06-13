"""Post-render HTML/CSS lint and deterministic repair.

The renderer is an LLM, and its most damaging failure mode observed in practice is CSS
that hides content forever: elements set `opacity: 0` and rely on an animation to fade
in, but the `animation-name` points at a @keyframes block that was never emitted — the
animation never runs and the content ships invisible.

This module is the safety net (deterministic code, no LLM):
  - find_issues(html)  -> list of human-readable problems (empty = clean)
  - repair(html)       -> (fixed_html, list of applied fixes), guaranteed renderable

The render step re-rolls the LLM up to MAX_RENDER_ATTEMPTS times on lint failure and
falls back to repair() so a broken page can never ship.
"""

import re
import logging

logger = logging.getLogger(__name__)

# Keywords that may appear in the `animation` shorthand and are never keyframes names.
_ANIMATION_KEYWORDS = {
    "ease", "linear", "ease-in", "ease-out", "ease-in-out", "step-start", "step-end",
    "infinite", "forwards", "backwards", "both", "none", "normal", "reverse",
    "alternate", "alternate-reverse", "running", "paused", "initial", "inherit",
    "unset", "revert", "auto",
}

_TIME_OR_NUMBER = re.compile(r"^-?\d*\.?\d+(m?s)?$")


def _styles(html: str) -> str:
    return "\n".join(re.findall(r"<style[^>]*>(.*?)</style>", html, re.S | re.I))


def _defined_keyframes(css: str) -> set[str]:
    return set(re.findall(r"@keyframes\s+([\w-]+)", css))


def _used_animation_names(css: str) -> set[str]:
    used: set[str] = set()

    # Explicit `animation-name: a, b;`
    for value in re.findall(r"animation-name\s*:\s*([^;}]+)", css):
        for name in value.split(","):
            name = name.strip()
            if name and name.lower() not in _ANIMATION_KEYWORDS:
                used.add(name)

    # Shorthand `animation: 0.6s ease-out forwards fadeIn, ...;`
    for value in re.findall(r"animation\s*:\s*([^;}]+)", css):
        for layer in value.split(","):
            # Drop functional tokens like cubic-bezier(...) / steps(...)
            layer = re.sub(r"[\w-]+\([^)]*\)", " ", layer)
            for token in layer.split():
                if token.lower() in _ANIMATION_KEYWORDS:
                    continue
                if _TIME_OR_NUMBER.match(token):
                    continue
                if re.fullmatch(r"[a-zA-Z][\w-]*", token):
                    used.add(token)
    return used


def find_issues(html: str) -> list[str]:
    """Deterministic checks for failure modes that make a page unusable."""
    issues: list[str] = []

    if not html.rstrip().endswith("</html>"):
        issues.append("document truncated: missing closing </html>")

    css = _styles(html)
    if css:
        missing = _used_animation_names(css) - _defined_keyframes(css)
        for name in sorted(missing):
            issues.append(f"animation-name '{name}' has no matching @keyframes (content may stay invisible)")

    return issues


def repair(html: str) -> tuple[str, list[str]]:
    """Deterministically fix what find_issues() flagged. Guaranteed-visible output:
    missing keyframes are injected as a fade-to-visible so `forwards` fill leaves the
    element at full opacity and neutral transform."""
    fixes: list[str] = []

    css = _styles(html)
    if css:
        missing = sorted(_used_animation_names(css) - _defined_keyframes(css))
        if missing:
            injected = "\n".join(
                f"@keyframes {name} {{ to {{ opacity: 1; transform: none; }} }}"
                for name in missing
            )
            # Inject into the last </style> so the rules apply document-wide.
            idx = html.lower().rfind("</style>")
            if idx != -1:
                html = html[:idx] + "\n/* injected by post-render lint */\n" + injected + "\n" + html[idx:]
                fixes.append(f"injected missing @keyframes: {', '.join(missing)}")

    if not html.rstrip().endswith("</html>"):
        html = html.rstrip() + "\n</body>\n</html>\n"
        fixes.append("appended missing </body></html>")

    return html, fixes
