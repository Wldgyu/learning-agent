"""Convert stored answer markup into plain text for display, without changing grading."""

from html.parser import HTMLParser


class AnswerTextParser(HTMLParser):
    blocks = {"p", "div", "li", "ul", "ol", "blockquote", "tr", "h1", "h2", "h3", "h4"}

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.lines = []
        self.parts = []
        self.hidden = 0
        self.pre = 0

    def flush(self, blank=False):
        raw = "".join(self.parts).replace("\xa0", " ")
        value = raw if self.pre else " ".join(raw.split())
        self.parts.clear()
        if value.strip():
            self.lines.append(value)
        elif blank and self.lines and self.lines[-2:] != ["", ""]:
            self.lines.append("")

    def handle_starttag(self, tag, attrs):
        if tag in {"script", "style"}:
            self.hidden += 1
        if self.hidden:
            return
        if tag == "pre":
            self.flush()
            self.pre += 1
        elif tag == "br":
            if self.pre:
                self.parts.append("\n")
            else:
                self.flush(blank=True)
        elif not self.pre and tag in self.blocks:
            self.flush()

    def handle_endtag(self, tag):
        if self.hidden:
            if tag in {"script", "style"}:
                self.hidden -= 1
            return
        if tag == "pre":
            self.flush()
            self.pre = max(0, self.pre - 1)
        elif not self.pre and tag in self.blocks:
            self.flush(blank=tag == "p")
        elif not self.pre and tag in {"td", "th"}:
            self.parts.append("  ")

    def handle_data(self, data):
        if not self.hidden:
            self.parts.append(data)


def format_answer(markup: str, fallback: str) -> str:
    if not markup:
        return fallback
    parser = AnswerTextParser()
    parser.feed(markup)
    parser.close()
    parser.flush()
    return "\n".join(parser.lines).strip() or fallback
