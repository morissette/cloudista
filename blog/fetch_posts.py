#!/usr/bin/env python3
"""
Fetch all mattharris.org blog posts from archive.org and save as .txt files.
"""

import os
import re
import time
import urllib.request
from html.parser import HTMLParser

POSTS = [
    ("2014/08/appcpanminus-skinny", "20140814015954"),
    ("2014/08/bash-loops", "20140814015959"),
    ("2014/08/centering-rotated-elements", "20140814020004"),
    ("2014/08/contact-form-7-sending-e-mail", "20140812220404"),
    ("2014/08/first-plugin-for-tinymce", "20140920033151"),
    ("2014/08/htmlpurifier-truncating-output", "20140814020014"),
    ("2014/08/importing-spreadsheets-with-phpexcel", "20150626091003"),
    ("2014/08/perl-tutorials-coming-soon", "20140814020019"),
    ("2014/08/scrum-point-cards-google-hangouts-extension", "20140814020024"),
    ("2014/09/mac-osx-homebrew-shellshock-fix", "20150217021826"),
    ("2014/09/mysql-basic-design-concepts", "20150217004650"),
    ("2014/10/python-authentication-wordpress", "20141021051032"),
    ("2015/06/apache-not-serving-pages-selinux", "20150623071706"),
    ("2015/06/installing-mean-stack-on-amazon-linux", "20150701162622"),
    ("2015/06/mysql-tip-cli-authentication-bypass-password", "20150623130713"),
    ("2015/06/selenium-testing-basics-with-ruby", "20150623120222"),
    ("2015/06/trello-api-basics", "20150624062855"),
    ("2015/07/logging-the-correct-ip-to-apache-over-varnish-and-cloudflare", "20150717224642"),
    ("2015/07/setting-up-tornado-w-nginx", "20150724123239"),
    ("2015/08/cucm-details-with-axl-and-risport-via-python", "20150815043950"),
    ("2015/08/running-docker-as-a-jail-for-unsanitized-code", "20151118013723"),
    ("2015/08/scrolling-divs-in-bootstrap-with-100-height", "20160323222018"),
    ("2015/09/monitoring-with-shinken", "20150905174444"),
    ("2015/09/when-spam-is-a-necessary-evil", "20150930172748"),
    ("2015/10/amazon-boto3-library-for-python-basics", "20151013034809"),
    ("2015/10/bitnami-alfresco-failing-to-start", "20151021004905"),
    ("2015/10/fixing-sqlalchemy-mysql-errors-on-restart-of-uwsgi", "20151010021205"),
    ("2015/10/log_warning_msg-not-found-on-init-script-shinken", "20151008051259"),
    ("2015/10/parsing-craigslist-for-an-item-across-multiple-cities", "20151020030823"),
    ("2015/10/simple-website-backups-to-aws-s3", "20151015014628"),
    ("2015/10/writing-a-simple-shinken-log-check-over-ssh", "20151021072015"),
    ("2015/11/angular-datatables-with-an-ajax-source", "20151207035821"),
    ("2015/11/cpanel-plugin-templating-basics", "20151120234117"),
    ("2015/11/jwt-tokens-not-recognized-on-aws-elasticbeanstalk", "20151125200304"),
    ("2015/11/setting-aws-elasticbeanstalk-environment-wsgi-authorization", "20151209001110"),
    ("2015/11/when-not-to-use-drupal-a-rant", "20151207035846"),
    ("2015/12/aws-sqs-boto3-basics", "20151225160641"),
    ("2015/12/bug-in-aws-console-s3", "20151208162641"),
    ("2015/12/dynamodb-boto3-example", "20151230170637"),
    ("2015/12/installing-omd-on-amazon-linux", "20151225154549"),
    ("2015/12/jquery-javascript-hacking-linkedin-profile", "20151225101024"),
    ("2015/12/mysql-server-has-gone-away-on-import", "20151207035923"),
    ("2016/01/aws-client-error-malformedcertificate-unable-to-parse-certificate", "20160206105009"),
    ("2016/01/fedora-redhat-facebook-messenger-in-pidgin", "20160206134749"),
    ("2016/01/monit-keep-your-services-running-on-your-server", "20160204111232"),
    ("2016/01/python-authenticating-with-azure-rest-api", "20160204143703"),
    ("2016/02/angularjs-how-to-pass-data-between-controllers", "20160227200900"),
    ("2016/02/bitbucket-and-codedeploy", "20160304104404"),
    ("2016/02/http-2-4-ah00051-child-pid-22471-exit-signal-segmentation-fault-11", "20160227120658"),
    ("2016/02/introduction-aws-lambda", "20160306122915"),
    ("2016/02/manually-aborting-a-elasticbeanstalk-deployment", "20160206051019"),
    ("2016/02/vim-as-an-ide", "20160402134735"),
    ("2016/03/logging-sites-perl-python", "20160402111607"),
    ("2016/03/logstash-install-amazon-linux", "20160323021958"),
    ("2016/03/mailchimp-add-email-subscription-list-python", "20160318135536"),
    ("2016/03/route53-ip-update-automation", "20160323000637"),
    ("2016/03/setup-slack-notifications-aws-codedeploy", "20160321165556"),
    ("2016/04/angular-auto-populate-location-data-based-zipcode", "20160423112825"),
    ("2016/04/aws-swf-tutorial-python", "20160406220652"),
    ("2016/04/installing-pandas-t2-micro-aws-instance", "20160421211239"),
    ("2016/05/ocr-basics-reading-business-card", "20160527080355"),
    ("2016/05/return-default-variable-golang", "20160525164556"),
    ("2016/06/design-ha-cloud", "20160629224719"),
    ("2016/06/dockerize-flask-app-w-nginx-uwsgi", "20160627020712"),
    ("2016/06/dockerizing-symfony-application", "20161203074438"),
    ("2016/06/elastic-beanstalk-error-cannot-500-application-versions", "20160602000425"),
    ("2016/06/one-line-bash-script-go-unasked-challenge", "20160626005050"),
    ("2016/06/upgrading-omd-1-20-1-30", "20160624123632"),
    ("2016/07/amazons-machine-learning-engine-prime-music-horrible-non-existent", "20161016163119"),
    ("2016/07/kong-with-kubernetes", "20161009020521"),
    ("2016/08/deploying-jenkins-kubernetes-cluster", "20161203071616"),
]

OUTPUT_DIR = os.path.dirname(os.path.abspath(__file__))


class ContentExtractor(HTMLParser):
    """Extract article content from WordPress HTML."""

    def __init__(self):
        super().__init__()
        self.in_article = False
        self.in_entry_content = False
        self.in_entry_title = False
        self.in_entry_date = False
        self.depth = 0
        self.article_depth = 0
        self.content_depth = 0
        self.title = ""
        self.date = ""
        self.content_parts = []
        self.skip_tags = {'script', 'style', 'nav', 'header', 'footer'}
        self.skip_depth = 0
        self.current_tag_stack = []
        self.in_code = False
        self.code_buffer = ""
        self.in_pre = False

    def handle_starttag(self, tag, attrs):
        attrs_dict = dict(attrs)
        classes = attrs_dict.get('class', '').split()

        self.current_tag_stack.append(tag)
        self.depth += 1

        if tag in self.skip_tags and not self.in_article:
            self.skip_depth = self.depth
            return

        article_classes = ['post', 'hentry', 'entry', 'post-content', 'single-post']
        if tag == 'article' or (tag in ('div', 'section') and any(c in classes for c in article_classes)):
            self.in_article = True
            self.article_depth = self.depth

        if self.in_article:
            title_classes = ['entry-title', 'post-title', 'title']
            content_classes = ['entry-content', 'post-content', 'post-body', 'the-content']
            if tag in ('h1', 'h2') and any(c in classes for c in title_classes):
                self.in_entry_title = True
            elif tag == 'time' or (
                tag in ('span', 'p', 'div')
                and any(c in classes for c in ['entry-date', 'post-date', 'date', 'published'])
            ):
                self.in_entry_date = True
            elif tag == 'div' and any(c in classes for c in content_classes):
                self.in_entry_content = True
                self.content_depth = self.depth
            elif tag == 'pre' and self.in_entry_content:
                self.in_pre = True
                self.content_parts.append('\n```\n')
            elif tag == 'code' and self.in_entry_content and not self.in_pre:
                self.in_code = True
                self.content_parts.append('`')
            elif tag in ('p', 'li', 'h1', 'h2', 'h3', 'h4', 'h5', 'h6') and self.in_entry_content:
                if tag.startswith('h'):
                    level = int(tag[1])
                    self.content_parts.append('\n' + '#' * level + ' ')
                elif tag == 'p':
                    self.content_parts.append('\n')
                elif tag == 'li':
                    self.content_parts.append('\n- ')
            elif tag == 'br' and self.in_entry_content:
                self.content_parts.append('\n')

    def handle_endtag(self, tag):
        if self.depth == self.skip_depth:
            self.skip_depth = 0

        if self.in_pre and tag == 'pre':
            self.in_pre = False
            self.content_parts.append('\n```\n')
        elif self.in_code and tag == 'code':
            self.in_code = False
            self.content_parts.append('`')
        elif self.in_entry_title and tag in ('h1', 'h2', 'span', 'a'):
            self.in_entry_title = False
        elif self.in_entry_date and tag in ('time', 'span', 'p', 'div', 'a'):
            self.in_entry_date = False
        elif self.in_entry_content and self.depth == self.content_depth:
            self.in_entry_content = False

        if self.current_tag_stack:
            self.current_tag_stack.pop()
        self.depth -= 1

        if self.in_article and self.depth < self.article_depth:
            self.in_article = False

    def handle_data(self, data):
        if self.skip_depth:
            return
        if self.in_entry_title:
            self.title += data
        elif self.in_entry_date:
            self.date += data.strip()
        elif self.in_entry_content:
            self.content_parts.append(data)

    def get_content(self):
        return ''.join(self.content_parts)


def fetch_wayback(slug, timestamp):
    """Fetch a page from the Wayback Machine."""
    url = f"https://web.archive.org/web/{timestamp}/http://mattharris.org/{slug}/"
    req = urllib.request.Request(
        url,
        headers={
            'User-Agent': 'Mozilla/5.0 (compatible; blog-archiver/1.0)',
        }
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            html = resp.read().decode('utf-8', errors='replace')
            return html
    except Exception:
        return None


def html_to_text(html, slug, timestamp):
    """Convert HTML to readable text, extracting the article content."""
    parser = ContentExtractor()
    try:
        parser.feed(html)
    except Exception:
        pass

    title = parser.title.strip() or slug.split('/')[-1].replace('-', ' ').title()
    date_str = parser.date.strip()

    # Try to extract date from slug if not found
    if not date_str:
        m = re.match(r'(\d{4})/(\d{2})/', slug)
        if m:
            date_str = f"{m.group(1)}-{m.group(2)}"

    content = parser.get_content()

    # Clean up whitespace
    content = re.sub(r'\n{4,}', '\n\n\n', content)
    content = content.strip()

    # If content extraction failed (WordPress sometimes has different structure),
    # try a simpler regex-based extraction
    if len(content) < 100:
        # Fallback: extract all text between common content markers
        m = re.search(
            r'<div[^>]*class="[^"]*entry-content[^"]*"[^>]*>(.*?)</div>\s*</div>\s*</article',
            html, re.DOTALL,
        )
        if not m:
            m = re.search(r'<div[^>]*class="[^"]*post-content[^"]*"[^>]*>(.*?)</div>\s*</div>', html, re.DOTALL)
        if m:
            raw = m.group(1)
            # Strip tags
            raw = re.sub(r'<[^>]+>', ' ', raw)
            raw = re.sub(r'&amp;', '&', raw)
            raw = re.sub(r'&lt;', '<', raw)
            raw = re.sub(r'&gt;', '>', raw)
            raw = re.sub(r'&nbsp;', ' ', raw)
            raw = re.sub(r'&#\d+;', '', raw)
            raw = re.sub(r'&[a-z]+;', '', raw)
            raw = re.sub(r'\s+', ' ', raw).strip()
            content = raw

    # Clean HTML entities
    content = re.sub(r'&amp;', '&', content)
    content = re.sub(r'&lt;', '<', content)
    content = re.sub(r'&gt;', '>', content)
    content = re.sub(r'&nbsp;', ' ', content)
    content = re.sub(r'&#8217;', "'", content)
    content = re.sub(r'&#8216;', "'", content)
    content = re.sub(r'&#8220;', '"', content)
    content = re.sub(r'&#8221;', '"', content)
    content = re.sub(r'&#8211;', '-', content)
    content = re.sub(r'&#8212;', '--', content)
    content = re.sub(r'&#\d+;', '', content)
    content = re.sub(r'&[a-z]+;', '', content)

    output = f"Title: {title}\n"
    if date_str:
        output += f"Date: {date_str}\n"
    output += f"URL: https://mattharris.org/{slug}/\n"
    output += f"Archive: https://web.archive.org/web/{timestamp}/http://mattharris.org/{slug}/\n"
    output += "\n" + "="*60 + "\n\n"
    output += content

    return output


def slug_to_filename(slug):
    """Convert slug to a safe filename."""
    # e.g. "2014/08/bash-loops" -> "2014-08-bash-loops.txt"
    return slug.replace('/', '-') + '.txt'


def main():
    os.makedirs(OUTPUT_DIR, exist_ok=True)

    total = len(POSTS)
    success = 0
    failed = []

    for i, (slug, timestamp) in enumerate(POSTS, 1):
        filename = slug_to_filename(slug)
        filepath = os.path.join(OUTPUT_DIR, filename)

        if os.path.exists(filepath) and os.path.getsize(filepath) > 200:
            print(f"[{i}/{total}] SKIP (exists): {slug}")
            success += 1
            continue

        print(f"[{i}/{total}] Fetching: {slug} @ {timestamp}", flush=True)

        html = fetch_wayback(slug, timestamp)
        if not html:
            print("  ERROR: Failed to fetch")
            failed.append(slug)
            time.sleep(2)
            continue

        text = html_to_text(html, slug, timestamp)

        if len(text) < 300:
            print(f"  WARNING: Content seems short ({len(text)} chars)")

        with open(filepath, 'w', encoding='utf-8') as f:
            f.write(text)

        print(f"  OK: {len(text)} chars -> {filename}")
        success += 1

        # Be polite to archive.org
        time.sleep(1.5)

    print(f"\nDone: {success}/{total} succeeded")
    if failed:
        print(f"Failed ({len(failed)}):")
        for s in failed:
            print(f"  {s}")


if __name__ == '__main__':
    main()
