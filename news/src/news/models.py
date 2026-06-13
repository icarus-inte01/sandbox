from dataclasses import dataclass, field


@dataclass
class Article:
    title: str
    url: str
    description: str
    source_name: str
    published: str
    region: str


@dataclass
class FeedConfig:
    url: str
    source: str


@dataclass
class RegionConfig:
    name: str
    feeds: list[FeedConfig] = field(default_factory=list)
