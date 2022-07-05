import time
import sys
import json
import os
import random
import re
import threading

from prawcore.exceptions import Forbidden
from praw.models import Comment
from praw.exceptions import RedditAPIException
import praw

import secrets

import logging
logging.basicConfig(
        filename="bot.log",
        level=logging.INFO,
        format='%(asctime)s %(levelname)-8s %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S')

SHITPOST_THRESHOLD = 4


################################## actual code #################################

class HPBot():

    def __init__(self):
        config = None
        with open('reddit_config.json') as f:
            config = json.loads(f.read())

        self.INCLUDED_SUBS = config['INCLUDED_SUBS']
        self.EXCLUDED_USERS, self.EXCLUDED_SUBS = config['EXCLUDED_USERS'], config['EXCLUDED_SUBS']
        self.EXCLUDED_USERS.append('thebenshapirobotbot')
        self.EXCLUDED_USERS.append('thehasanpikerbot')
        self.EXCLUDED_USERS.append('automoderator')
        self.config = config # Cache for later saving

        self.load_pundits()

        self.r = praw.Reddit(
            client_id=secrets.CLIENT_ID,
            client_secret=secrets.SECRET,
            user_agent=f'{secrets.USERNAME} (by /u/thehasanpikerbot)',
            username=secrets.USERNAME,
            password=secrets.PASSWORD,
            ratelimit_seconds=config['ratelimit_seconds']
        )
        self.opt_out_submission = praw.models.Submission(self.r, id='vqxa9h')

    def load_pundits(self):
        pundits_basedir = 'pundits'
        pundit_files = [pundit_file for pundit_file in os.listdir(pundits_basedir) if pundit_file.endswith('.json')]
        
        # Load files into pundits dic
        self.pundits = {}
        for pundit_file in pundit_files:
            pundit_name = pundit_file.rstrip('.json')
            with open(os.path.join(pundits_basedir, pundit_file)) as f:
                self.pundits[pundit_name] = json.load(f)

    def generate_footnote(self, pundit_name='Hasan Piker'):
        options = [o.lower() for o in self.pundits[pundit_name]['shitposts'].keys()]
        options = ', '.join(options)
        options = f'{options}, etc.'
        return self.pundits[pundit_name]['footnote'].format(options=options)

    def handle_opt_outs(self):
        replies = []
        for comment in self.opt_out_submission.comments:
            try:
                comment.refresh()
            except praw.exceptions.ClientException as e:
                sys.stderr.write(f'Could not refresh comment {comment}. Exception: {e}')
                continue

            if comment.author is None:
                continue
            elif comment.author.name.lower() in self.EXCLUDED_USERS:
                continue

            replies.append(
                self.reply_if_appropriate(comment, 'OPT-OUT')
            )

            self.EXCLUDED_USERS.append(comment.author.name.lower())
            self.save_reddit_config()
            logging.debug(f'Opting out user {comment.author.name}')

        return replies

    def save_reddit_config(self):
        config = self.config
        config['EXCLUDED_USERS'] = list(set(self.EXCLUDED_USERS))
        config['EXCLUDED_SUBS'] = list(set(self.EXCLUDED_SUBS))
        config['INCLUDED_SUBS'] = list(set(self.INCLUDED_SUBS))
        with open('reddit_config.json', 'w+') as f:
            f.write(json.dumps(config, indent=2))

    def clean_comment(self, comment):
        return ' '.join(w.lower() for w in comment.body.split())

    def extract_keyword_from_comment(self, comment, pundit_name='Hasan Piker'):
        words = self.clean_comment(comment)
        for word in self.pundits[pundit_name]['shitposts'].keys():
            if word.lower() in words:
                logging.debug(f'Extracted keyword {word} from comment')
                return word
        return None

    def get_shitpost_message(self, comment, pundit_name='Hasan Piker'):
        key = self.extract_keyword_from_comment(comment)
        if key is None:
            key = random.choice(list(self.pundits[pundit_name]['shitposts'].keys()))

        message = random.choice(self.pundits[pundit_name]['shitposts'][key])
        message = f'*{message}*\n\n\n -{pundit_name}'
        return message

    def should_shitpost(self, submission):
        i = 0
        me = praw.models.Redditor(self.r, name=secrets.USERNAME)
        for i, my_comment in enumerate(me.comments.new(limit=50)):
            if my_comment.submission.id == submission.id:
                i += 1
                if i >= SHITPOST_THRESHOLD:
                    return True
        return False

    def reply_if_appropriate(self, comment, message_type, pundit_name='Hasan Piker'):
        try:
            comment.refresh()
        except (praw.exceptions.ClientException, AttributeError) as e:
            sys.stderr.write(f'Could not refresh comment {comment}. Exception: {e}')
            return

        if (
                secrets.USERNAME.lower() in
                [
                    r.author.name.lower() for r in comment.replies
                    if r.author is not None
                ]
        ):
            return

        if comment.author is not None:
            if comment.author.name.lower() in self.EXCLUDED_USERS:
                if message_type != 'OPT-OUT':
                    return

        message = None
        quotes = self.pundits[pundit_name]['quotes']
        template = self.pundits[pundit_name]['template']
        good_bot_replies = self.pundits[pundit_name]['good_bot']
        bad_bot_replies = self.pundits[pundit_name]['bad_bot']
        template_args = {'replying_username': comment.author.name}
        if message_type == 'GENERIC':
            if self.should_shitpost(comment.submission):
                return self.reply_if_appropriate(comment, 'SHITPOST', pundit_name=pundit_name)

            message = template.format(
                quote=random.choice(quotes)
            )
        elif message_type in ('SHITPOST', 'SUMMONS'):
            message = self.get_shitpost_message(comment, pundit_name=pundit_name)
        elif message_type == 'GOOD-BOT-REPLY':
            message = random.choice(good_bot_replies)
        elif message_type == 'BAD-BOT-REPLY':
            message = random.choice(bad_bot_replies)
        elif message_type == 'OPT-OUT':
            message = random.choice(bad_bot_replies)
        else:
            raise ValueError(f'Invalid message_type {message_type}')

        message = '\n\n'.join((message, self.generate_footnote(pundit_name=pundit_name)))
        message = message.format(**template_args)
        result = None
        try:
            result = comment.reply(body=message)
            logging.info(f'Made comment {result.permalink}')
        except Exception as e:
            if type(e) is Forbidden:
                self.EXCLUDED_SUBS.append(comment.subreddit.display_name)
                self.save_reddit_config()
                sys.stderr.write(
                    f'Found new banned subreddit {comment.subreddit.display_name}'
                )
            elif type(e) is RedditAPIException:
                # for now, probably handle differently later?
                sys.stderr.write(
                    f'Reply failed with exception {e}'
                )
            else:
                sys.stderr.write(
                    f'Reply failed with exception {e}'
                )

        return result

    def respond(self, comment):
        submission_id = None
        try:
            submission_id = comment.submission.id
        except AttributeError as e:
            # some kinds of messages arne't associated with
            # subreddits.
            pass

        text = self.clean_comment(comment)
        response = None
        if submission_id == self.opt_out_submission.id:
            self.EXCLUDED_USERS.append(comment.author.name.lower())
            self.save_reddit_config()
            response = self.reply_if_appropriate(comment, 'OPT-OUT')
        elif 'good bot' in text:
            response = self.reply_if_appropriate(comment, 'GOOD-BOT-REPLY')
        elif 'bad bot' in text:
            response = self.reply_if_appropriate(comment, 'BAD-BOT-REPLY')
        else:
            key = self.extract_keyword_from_comment(comment)
            if key is None:
                response = self.reply_if_appropriate(comment, 'GENERIC')
            else:
                response = self.reply_if_appropriate(comment, 'SUMMONS')

        if response is not None:
            comment.mark_read()

    def inbox_stream_thread(self):
        logging.info('Starting inbox_stream_thread')
        for item in self.r.inbox.stream():
            logging.debug(f'Found unread mail {repr(item)}')
            if isinstance(item, Comment):
                self.respond(item)
        logging.info('End of inbox_stream_thread')

    def create_subs_string(self):
        result = '+'.join(self.INCLUDED_SUBS)
        if len(self.EXCLUDED_SUBS) > 0:
            result += f'-{"-".join(self.EXCLUDED_SUBS)}'
        logging.info(f'Subs string created: {result}')
        return result

    def subreddit_stream_thread(self):
        logging.info('Starting subreddit_stream_thread')
        pundit_names = [(pundit_name.lower(), pundit_name) for pundit_name in self.pundits.keys()]
        for i, comment in enumerate(self.r.subreddit(self.create_subs_string()).stream.comments()):
            if (
                    comment.author.name.lower() == secrets.USERNAME or
                    comment.subreddit.display_name.lower() in self.EXCLUDED_SUBS
            ):
                continue

            words = self.clean_comment(comment)
            result = None
            for pundit_name in pundit_names:
                if pundit_name[0] in words:
                    result = self.reply_if_appropriate(comment, 'GENERIC', pundit_name=pundit_name[1])
        logging.info('End of subreddit_stream_thread')

    def main(self):
        logging.info('Start of main function')
        subreddit_thread = threading.Thread(target=self.subreddit_stream_thread, args=() )
        inbox_thread = threading.Thread(target=self.inbox_stream_thread, args=() )

        subreddit_thread.start()
        inbox_thread.start()
        logging.info('End of main function')

if __name__ == '__main__':
    HPBot().main()
