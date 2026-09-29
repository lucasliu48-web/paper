"""Publish recent PubMed citations for the configured research terms."""

import datetime
import json
import re
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from email.utils import format_datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent
BASE = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/"
LIMIT = 60
DC = "http://purl.org/dc/elements/1.1/"


def fetch(name, params):
    url = BASE + name + "?" + urllib.parse.urlencode({**params, "tool": "paper_feed"})
    request = urllib.request.Request(url, headers={"User-Agent": "paper-feed/1.0"})
    with urllib.request.urlopen(request, timeout=90) as response:
        return response.read()


def publication_date(article):
    for path in ("./MedlineCitation/Article/ArticleDate",
                 "./MedlineCitation/Article/Journal/JournalIssue/PubDate",
                 "./BookDocument/Book/PubDate"):
        node = article.find(path)
        if node is None:
            continue
        year = node.findtext("Year")
        if not year:
            medline = node.findtext("MedlineDate") or ""
            match = re.search(r"\b(?:19|20)\d{2}\b", medline)
            year = match.group(0) if match else None
        if not year:
            continue
        month = node.findtext("Month") or "1"
        if not month.isdigit():
            names = "Jan Feb Mar Apr May Jun Jul Aug Sep Oct Nov Dec".split()
            month = str(names.index(month[:3].title()) + 1) if month[:3].title() in names else "1"
        try:
            return datetime.datetime(int(year), int(month), int(node.findtext("Day") or 1))
        except ValueError:
            return datetime.datetime(int(year), 1, 1)
    return None


def main():
    terms = [line.strip() for line in (ROOT / "keywords.dat").read_text(encoding="utf-8").splitlines()
             if line.strip() and not line.lstrip().startswith("#")]
    if not terms:
        raise ValueError("keywords.dat is empty")
    query = " OR ".join(f'"{term.replace(chr(34), "")}"[Title/Abstract]' for term in terms)
    result = json.loads(fetch("esearch.fcgi", {
        "db": "pubmed", "term": f"({query})", "retmode": "json",
        "retmax": LIMIT, "sort": "pub_date",
    }))
    search = result.get("esearchresult", {})
    pmids = search.get("idlist", [])
    if not pmids or not all(pmid.isdigit() for pmid in pmids):
        raise ValueError("PubMed search returned no valid PMIDs")
    root = ET.fromstring(fetch("efetch.fcgi", {
        "db": "pubmed", "id": ",".join(pmids), "retmode": "xml",
    }))
    articles = {a.findtext("./MedlineCitation/PMID"): a for a in root.findall("PubmedArticle")}
    articles.update({a.findtext("./BookDocument/PMID"): a for a in root.findall("PubmedBookArticle")})
    if set(articles) != set(pmids):
        missing = ",".join(sorted(set(pmids) - set(articles)))
        raise ValueError(f"PubMed records do not match search results; missing PMIDs: {missing}")

    items = []
    for pmid in pmids:
        article = articles[pmid]
        title_node = article.find("./MedlineCitation/Article/ArticleTitle")
        if title_node is None:
            title_node = article.find("./BookDocument/ArticleTitle")
        title = "".join(title_node.itertext()).strip() if title_node is not None else ""
        journal = (article.findtext("./MedlineCitation/Article/Journal/Title")
                   or article.findtext("./BookDocument/Book/BookTitle") or "PubMed")
        if not title:
            continue
        doi = next((node.text for node in article.findall(".//ArticleIdList/ArticleId")
                    if node.get("IdType") == "doi" and node.text), "")
        kinds = [node.text for node in article.findall("./MedlineCitation/Article/PublicationTypeList/PublicationType")
                 if node.text]
        if article.tag == "PubmedBookArticle":
            kinds = ["Book chapter"]
        description = f"PMID: {pmid}. " + (f"DOI: {doi}. " if doi else "")
        description += f"类型: {', '.join(kinds[:3]) or '未标注'}。摘要请查看 PubMed 原始记录。"
        link = f"https://pubmed.ncbi.nlm.nih.gov/{pmid}/"
        items.append({"title": title, "link": link, "description": description,
                      "date": publication_date(article), "journal": journal})
    ET.register_namespace("dc", DC)
    rss = ET.Element("rss", {"version": "2.0"})
    channel = ET.SubElement(rss, "channel")
    for name, value in {
        "title": "加兰他敏文献追踪",
        "link": "https://lucasliu48-web.github.io/paper/",
        "description": "PubMed recent citations matching the configured terms; metadata only",
        "language": "zh-CN",
        "lastBuildDate": format_datetime(datetime.datetime.now(datetime.timezone.utc)),
    }.items():
        ET.SubElement(channel, name).text = value
    for paper in items:
        node = ET.SubElement(channel, "item")
        for name in ("title", "link", "description"):
            ET.SubElement(node, name).text = paper[name]
        ET.SubElement(node, "guid", {"isPermaLink": "true"}).text = paper["link"]
        if paper["date"]:
            ET.SubElement(node, "pubDate").text = format_datetime(
                paper["date"].replace(tzinfo=datetime.timezone.utc))
        ET.SubElement(node, f"{{{DC}}}source").text = paper["journal"]
    ET.ElementTree(rss).write(ROOT / "filtered_feed.xml", encoding="utf-8", xml_declaration=True)
    print(f"PubMed total matches: {search.get('count')}; published {len(items)} recent citations")


if __name__ == "__main__":
    main()
