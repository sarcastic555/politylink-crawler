from datetime import datetime
from logging import getLogger

import scrapy

from crawler.spiders import NewsSpiderTemplate
from crawler.utils import extract_json_ld_or_none, build_news, extract_thumbnail_or_none, \
    strip_join, to_neo4j_datetime, extract_full_href_list
from politylink.elasticsearch.schema import NewsText

LOGGER = getLogger(__name__)


class ReutersSpider(NewsSpiderTemplate):
    name = 'reuters'
    publisher = 'ロイター'

    def __init__(self, limit, *args, **kwargs):
        super(ReutersSpider, self).__init__(*args, **kwargs)
        self.limit = int(limit)
        self.news_count = 0
        self.next_page = 0

    def build_next_url(self):
        self.next_page += 1
        return f'https://jp.reuters.com/news/archive/politicsNews?view=page&page={self.next_page}&pageSize=10'

    def start_requests(self):
        yield scrapy.Request(self.build_next_url(), self.parse)

    def parse(self, response):
        news_url_list = extract_full_href_list(
            response.xpath('//section[@id="moreSectionNews"]//article'), response.url)
        LOGGER.info(f'scraped {len(news_url_list)} news urls from {response.url}')
        for news_url in news_url_list:
            yield response.follow(news_url, callback=self.parse_news)
        self.news_count += len(news_url_list)
        if self.news_count < self.limit:
            yield response.follow(self.build_next_url(), self.parse)

    def scrape_news_and_text(self, response):
        maybe_json_ld = extract_json_ld_or_none(response)
        title = response.xpath('//h1/text()').get().strip()
        body = strip_join(response.xpath('//div[@class="ArticleBodyWrapper"]/p/text()').getall())

        news = build_news(response.url, self.publisher)
        news.title = title
        news.is_paid = False
        if maybe_json_ld:
            json_ld = maybe_json_ld
            maybe_thumbnail = extract_thumbnail_or_none(json_ld)
            if maybe_thumbnail:
                news.thumbnail = maybe_thumbnail
            news.published_at = self.to_datetime(json_ld['datePublished'])
            news.last_modified_at = self.to_datetime(json_ld['dateModified'])

        news_text = NewsText({'id': news.id})
        news_text.title = title
        news_text.body = body

        return news, news_text

    @staticmethod
    def to_datetime(dt_str):
        return to_neo4j_datetime(datetime.strptime(dt_str, '%Y-%m-%dT%H:%M:%SZ'))
