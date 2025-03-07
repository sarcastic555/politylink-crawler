import json
from datetime import datetime
from logging import getLogger

import scrapy

from crawler.spiders import SpiderTemplate
from crawler.utils import build_minutes, build_speech, extract_topics, build_url, UrlTitle, build_minutes_activity

LOGGER = getLogger(__name__)


class MinutesSpider(SpiderTemplate):
    name = 'minutes'
    domain = 'ndl.go.jp'

    def __init__(self, start_date, end_date, speech='false', *args, **kwargs):
        super(MinutesSpider, self).__init__(*args, **kwargs)
        self.start_date = start_date
        self.end_date = end_date
        self.collect_speech = speech == 'true'
        self.next_pos = 1

    def build_next_url(self):
        return 'https://kokkai.ndl.go.jp/api/meeting?from={0}&until={1}&startRecord={2}&maximumRecords=5&recordPacking=JSON'.format(
            self.start_date, self.end_date, self.next_pos)

    def start_requests(self):
        yield scrapy.Request(self.build_next_url(), self.parse)

    def parse(self, response):
        """
        Minutes, Activity, Speech, UrlをGraphQLに保存する
        """

        LOGGER.info(f'requested {response.url}')
        response_body = json.loads(response.body)
        minutes_lst, activity_lst, speech_lst, url_lst = self.scrape_minutes_activities_speeches_urls(response_body)

        self.gql_client.bulk_merge(minutes_lst + activity_lst + speech_lst + url_lst)
        LOGGER.info(f'merged {len(minutes_lst)} minutes, {len(activity_lst)} activities, '
                    f'{len(speech_lst)} speeches, {len(url_lst)} urls')

        for minutes in minutes_lst:
            self.link_minutes(minutes)
        self.link_activities(activity_lst)
        self.link_speeches(speech_lst)
        self.link_urls(url_lst)

        self.next_pos = response_body['nextRecordPosition']
        if self.next_pos is not None:
            yield response.follow(self.build_next_url(), callback=self.parse)

    def scrape_minutes_activities_speeches_urls(self, response_body):
        minutes_lst, activity_lst, speech_lst, url_lst = [], [], [], []

        for meeting_rec in response_body['meetingRecord']:
            try:
                minutes = build_minutes(
                    meeting_rec['nameOfHouse'] + meeting_rec['nameOfMeeting'],
                    datetime.strptime(meeting_rec['date'], '%Y-%m-%d'))
                minutes.ndl_min_id = meeting_rec['issueID']
                topics = extract_topics(meeting_rec['speechRecord'][0]['speech'])
                if topics:
                    minutes.topics = topics
            except ValueError as e:
                LOGGER.warning(f'failed to parse minutes: {e}')
                continue
            minutes_lst.append(minutes)

            url = build_url(meeting_rec['meetingURL'], UrlTitle.HONBUN, self.domain)
            url.to_id = minutes.id
            url_lst.append(url)

            speakers = set()
            for speech_rec in meeting_rec['speechRecord']:
                speaker = speech_rec['speaker']
                speech = build_speech(minutes.id, int(speech_rec['speechOrder']))
                speech.speaker_name = speaker
                if self.collect_speech:
                    speech_lst.append(speech)
                if speaker not in speakers:
                    speakers.add(speaker)
                    try:
                        member = self.member_finder.find_one(speaker)
                    except Exception:
                        pass
                    else:
                        activity = build_minutes_activity(member.id, minutes.id, minutes.start_date_time)
                        url = build_url(speech_rec['speechURL'], UrlTitle.HONBUN, self.domain)
                        url.to_id = activity.id
                        activity_lst.append(activity)
                        url_lst.append(url)

        return minutes_lst, activity_lst, speech_lst, url_lst
