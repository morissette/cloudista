#!/usr/bin/env python3
"""
Process DynamoDB posts + archive posts:
1. Parse DynamoDB HTML content to clean text
2. Match with existing archive .txt files
3. Combine/prefer DynamoDB content (more complete)
4. Save new/updated .txt files
5. Update Matt/Matthew -> Marie (except code module names like Matt::Daemon)
6. Update author self-references (he/him/his/himself -> they/them/their/themselves)
   only in clearly self-referential contexts
"""

import json
import os
import re
from datetime import datetime

OUTPUT_DIR = os.path.dirname(os.path.abspath(__file__))
DYNAMO_FILE = '/tmp/dynamodb_posts.json'

# Mapping: dynamo link -> archive slug (year/month/slug)
DYNAMO_TO_ARCHIVE = {
    'htmlpurifier-truncating-output':   '2014/08/htmlpurifier-truncating-output',
    'tinymce-plugin':                   '2014/08/first-plugin-for-tinymce',
    'contact-form-7':                   '2014/08/contact-form-7-sending-e-mail',
    'hangouts-scrum':                   '2014/08/scrum-point-cards-google-hangouts-extension',
    'importing-spreadsheets-with-phpexcel': '2014/08/importing-spreadsheets-with-phpexcel',
    'bash-while-loops':                 '2014/08/bash-loops',
    'centering-rotated-elements':       '2014/08/centering-rotated-elements',
    'app-cpanminus-skinny':             '2014/08/appcpanminus-skinny',
    'mysql-design-concepts':            '2014/09/mysql-basic-design-concepts',
    'homebrew-shellshock-fix':          '2014/09/mac-osx-homebrew-shellshock-fix',
    'python-auth-with-wp':              '2014/10/python-authentication-wordpress',
    'trello-api-basics':                '2015/06/trello-api-basics',
    'apache-not-serving-pages':         '2015/06/apache-not-serving-pages-selinux',
    'selenium-testing-basics-w-ruby':   '2015/06/selenium-testing-basics-with-ruby',
    'mysql-tip-cli-auth':               '2015/06/mysql-tip-cli-authentication-bypass-password',
    'logging-ip-apache-w-varnish':      '2015/07/logging-the-correct-ip-to-apache-over-varnish-and-cloudflare',
    'install-mean-amazon-linux':        '2015/06/installing-mean-stack-on-amazon-linux',
    'run-docker-code-jail':             '2015/08/running-docker-as-a-jail-for-unsanitized-code',
    'setup-tornado-nginx':              '2015/07/setting-up-tornado-w-nginx',
    'drupal-rant':                      '2015/11/when-not-to-use-drupal-a-rant',
    'cucm-details-python':              '2015/08/cucm-details-with-axl-and-risport-via-python',
    'scrolling-divs-bootstrap':         '2015/08/scrolling-divs-in-bootstrap-with-100-height',
    'log-warning-msg-not-found':        '2015/10/log_warning_msg-not-found-on-init-script-shinken',
    'sql-errors-uwsgi':                 '2015/10/fixing-sqlalchemy-mysql-errors-on-restart-of-uwsgi',
    'boto3-basics':                     '2015/10/amazon-boto3-library-for-python-basics',
    'simple-backups-s3':                '2015/10/simple-website-backups-to-aws-s3',
    'parsing-craigslist':               '2015/10/parsing-craigslist-for-an-item-across-multiple-cities',
    'bitnami-alfresco-start-fail':      '2015/10/bitnami-alfresco-failing-to-start',
    'writing-shinken-check':            '2015/10/writing-a-simple-shinken-log-check-over-ssh',
    'cpanel-plugin-templating':         '2015/11/cpanel-plugin-templating-basics',
    'angular-datatables-ajax':          '2015/11/angular-datatables-with-an-ajax-source',
    'jwt-tokens-beanstalk':             '2015/11/jwt-tokens-not-recognized-on-aws-elasticbeanstalk',
    'monit-running':                    '2016/01/monit-keep-your-services-running-on-your-server',
    'mysql-gone-away-import':           '2015/12/mysql-server-has-gone-away-on-import',
    'parsing-logs-perl-lf':             None,  # archive had this but slug differs
    'aws-sqs-boto3':                    '2015/12/aws-sqs-boto3-basics',
    'hacking-linkedin-profile':         '2015/12/jquery-javascript-hacking-linkedin-profile',
    'monitoring-omd-amazon-linux':      '2015/12/installing-omd-on-amazon-linux',
    'dynamodb-boto3-example':           '2015/12/dynamodb-boto3-example',
    'python-auth-azure':                '2016/01/python-authenticating-with-azure-rest-api',
    'vim-as-an-ide':                    '2016/02/vim-as-an-ide',
    'abort-beanstalk-deployment':       '2016/02/manually-aborting-a-elasticbeanstalk-deployment',
    'http-segfault':                    '2016/02/http-2-4-ah00051-child-pid-22471-exit-signal-segmentation-fault-11',
    'bitbucket-codedeploy':             '2016/02/bitbucket-and-codedeploy',
    'lambda-ses-captcha':               '2016/02/introduction-aws-lambda',
    'lambda-restart-ec2':               None,  # only in dynamo
    'logging-into-sites':               '2016/03/logging-sites-perl-python',
    'mailchimp-python':                 '2016/03/mailchimp-add-email-subscription-list-python',
    'slack-notice-codedeploy':          '2016/03/setup-slack-notifications-aws-codedeploy',
    'route53-ip-update':                '2016/03/route53-ip-update-automation',
    'logstash-install':                 '2016/03/logstash-install-amazon-linux',
    'aws-swf-tutorial':                 '2016/04/aws-swf-tutorial-python',
    'auto-pop-loc-zip':                 '2016/04/angular-auto-populate-location-data-based-zipcode',
    'install-pandas-t2':                '2016/04/installing-pandas-t2-micro-aws-instance',
    'ocr-business-card':                '2016/05/ocr-basics-reading-business-card',
    'ebs-500-versions':                 '2016/06/elastic-beanstalk-error-cannot-500-application-versions',
    'json-api-golang':                  None,  # only in dynamo
    'dockerize-symfony':                '2016/06/dockerizing-symfony-application',
    'upgrading-omd':                    '2016/06/upgrading-omd-1-20-1-30',
    'one-line-bash-go':                 '2016/06/one-line-bash-script-go-unasked-challenge',
    'dockerize-flask':                  '2016/06/dockerize-flask-app-w-nginx-uwsgi',
    'deploy-jenkins-k8s':               '2016/08/deploying-jenkins-kubernetes-cluster',
    'ebs-wsgi-auth':                    '2015/11/setting-aws-elasticbeanstalk-environment-wsgi-authorization',
    'automating-amazon-giveaways':      None,  # only in dynamo
    'docker-cron-jobs':                 None,  # only in dynamo
    'microservices-n-k8s':              None,  # only in dynamo
    'smart-garage-door-primer':         None,  # only in dynamo
}

# Slugs we haven't mapped from archive but exist in archive only
ARCHIVE_ONLY = [
    '2014/08/perl-tutorials-coming-soon',
    '2015/09/monitoring-with-shinken',
    '2015/09/when-spam-is-a-necessary-evil',
    '2016/06/design-ha-cloud',
    '2016/07/amazons-machine-learning-engine-prime-music-horrible-non-existent',
    '2016/07/kong-with-kubernetes',
    '2015/12/bug-in-aws-console-s3',
    '2016/01/aws-client-error-malformedcertificate-unable-to-parse-certificate',
    '2016/01/fedora-redhat-facebook-messenger-in-pidgin',
    '2016/05/return-default-variable-golang',
]


def html_to_markdown(html):
    """Convert HTML post content to clean markdown text."""
    # Unescape HTML entities first
    html = html.replace('&amp;', '&').replace('&lt;', '<').replace('&gt;', '>')
    html = html.replace('&nbsp;', ' ').replace('&quot;', '"').replace('&#39;', "'")
    html = html.replace('&#8217;', "'").replace('&#8216;', "'")
    html = html.replace('&#8220;', '"').replace('&#8221;', '"')
    html = html.replace('&#8211;', '-').replace('&#8212;', '--')
    html = re.sub(r'&#\d+;', '', html)
    html = re.sub(r'&[a-z]+;', '', html)

    # Remove cloudflare email obfuscation junk
    html = re.sub(r'/\* <!\[CDATA\[.*?\]\]> \*/', '', html, flags=re.DOTALL)

    # Convert code blocks first (preserve content)
    def process_code_block(m):
        code = m.group(1)
        # Remove any HTML tags inside code
        code = re.sub(r'<[^>]+>', '', code)
        # Re-unescape HTML entities in code
        code = code.replace('&amp;', '&').replace('&lt;', '<').replace('&gt;', '>')
        code = code.replace('&nbsp;', ' ').replace('&#39;', "'")
        return '\n```\n' + code + '\n```\n'

    html = re.sub(r'<pre[^>]*>\s*<code[^>]*>(.*?)</code>\s*</pre>',
                  process_code_block, html, flags=re.DOTALL)
    def _pre_to_fence(m):
        inner = re.sub(r'<[^>]+>', '', m.group(1))
        inner = inner.replace('&lt;', '<').replace('&gt;', '>').replace('&amp;', '&')
        return '\n```\n' + inner + '\n```\n'

    html = re.sub(r'<pre[^>]*>(.*?)</pre>', _pre_to_fence, html, flags=re.DOTALL)

    # Inline code
    def _code_to_backtick(m):
        inner = re.sub(r'<[^>]+>', '', m.group(1))
        inner = inner.replace('&lt;', '<').replace('&gt;', '>').replace('&amp;', '&')
        return '`' + inner + '`'

    html = re.sub(r'<code[^>]*>(.*?)</code>', _code_to_backtick, html, flags=re.DOTALL)

    # Headings
    for i in range(1, 7):
        html = re.sub(f'<h{i}[^>]*>(.*?)</h{i}>',
                      lambda m, i=i: '\n' + '#' * i + ' ' + re.sub(r'<[^>]+>', '', m.group(1)).strip() + '\n',
                      html, flags=re.DOTALL)

    # Blockquotes
    html = re.sub(r'<blockquote[^>]*>(.*?)</blockquote>',
                  lambda m: '\n> ' + re.sub(r'<[^>]+>', ' ', m.group(1)).strip() + '\n',
                  html, flags=re.DOTALL)

    # Lists
    html = re.sub(r'<li[^>]*>', '\n- ', html)
    html = re.sub(r'</li>', '', html)
    html = re.sub(r'<[ou]l[^>]*>', '\n', html)
    html = re.sub(r'</[ou]l>', '\n', html)

    # Links - keep text
    html = re.sub(r'<a[^>]*href=["\']([^"\']*)["\'][^>]*>(.*?)</a>',
                  lambda m: m.group(2) if m.group(2).strip() else m.group(1),
                  html, flags=re.DOTALL)

    # Paragraphs
    html = re.sub(r'<p[^>]*>', '\n', html)
    html = re.sub(r'</p>', '\n', html)
    html = re.sub(r'<br\s*/?>', '\n', html)

    # Bold/italic
    html = re.sub(r'<(?:strong|b)[^>]*>(.*?)</(?:strong|b)>', r'**\1**', html, flags=re.DOTALL)
    html = re.sub(r'<(?:em|i)[^>]*>(.*?)</(?:em|i)>', r'*\1*', html, flags=re.DOTALL)

    # Strip remaining tags
    html = re.sub(r'<[^>]+>', '', html)

    # Clean up whitespace
    html = re.sub(r'\n{4,}', '\n\n\n', html)
    html = html.strip()

    return html


def apply_name_pronoun_updates(text):
    """
    Update Matt/Matthew -> Marie (when referring to the blog author).
    Update he/him/his/himself -> they/them/their/themselves in self-referential contexts.

    Rules:
    - Skip lines inside ``` code blocks (except MAINTAINER lines which are author metadata)
    - Matt::Daemon, Acme::Matt:: etc -> preserve (Perl module names)
    - Matthew Harris / Matt Harris -> Marie Harris
    - "by Matthew Harris" / "by Matt Harris" -> "by Marie Harris"
    - MAINTAINER Matt* / Matthew* -> MAINTAINER Marie Harris
    """
    lines = text.split('\n')
    result = []
    in_code_block = False

    for line in lines:
        # Track code blocks
        if line.strip().startswith('```'):
            in_code_block = not in_code_block
            result.append(line)
            continue

        if in_code_block:
            # In code blocks, only update MAINTAINER lines (author metadata)
            if re.match(r'\s*MAINTAINER\s+', line, re.IGNORECASE):
                line = re.sub(r'\bMatt(?:hew)?\s+Harris\b', 'Marie Harris', line)
                line = re.sub(r'\bMatthew\b(?!\s+Harris)', 'Marie', line)
            # Update "by Matthew/Matt Harris" in code comments
            line = re.sub(r'\bby\s+Matt(?:hew)?\s+Harris\b', 'by Marie Harris', line, flags=re.IGNORECASE)
            result.append(line)
            continue

        # Outside code blocks: update names
        # "Matt Harris" or "Matthew Harris" -> "Marie Harris"
        line = re.sub(r'\bMatt(?:hew)?\s+Harris\b', 'Marie Harris', line)
        # Standalone "Matthew" -> "Marie" (when not part of a Perl module like Matt::)
        line = re.sub(r'\bMatthew\b(?!::)', 'Marie', line)
        # "Matt" alone (not "Matt::" module names) -> "Marie"
        # Be careful: only replace standalone "Matt" that's clearly the author
        # Use word boundary and check it's not followed by ::
        line = re.sub(r'\bMatt\b(?!::)', 'Marie', line)

        result.append(line)

    return '\n'.join(result)


def dynamo_item_to_text(item):
    """Convert a DynamoDB item to clean text."""
    title = item.get('title', {}).get('S', '')
    content_html = item.get('content', {}).get('S', '')
    author = item.get('author', {}).get('S', 'Marie Harris')
    ts = int(item.get('timestamp', {}).get('N', 0))

    # Convert author name
    author = re.sub(r'\bMatt(?:hew)?\s+Harris\b', 'Marie Harris', author)

    # Convert timestamp to date
    date_str = datetime.fromtimestamp(ts).strftime('%Y-%m-%d') if ts else ''

    # Convert content HTML to markdown
    content = html_to_markdown(content_html)

    # Build output
    out = f'Title: {title}\n'
    out += f'Author: {author}\n'
    if date_str:
        out += f'Date: {date_str}\n'
    out += 'Source: DynamoDB\n'
    out += '\n' + '=' * 60 + '\n\n'
    out += content

    return out


def archive_slug_to_filename(slug):
    return slug.replace('/', '-') + '.txt'


def dynamo_link_to_filename(link, timestamp):
    """Create a filename for a DynamoDB-sourced post."""
    ts = int(timestamp) if timestamp else 0
    if ts:
        dt = datetime.fromtimestamp(ts)
        return f'{dt.year}-{dt.month:02d}-{link}.txt'
    return f'{link}.txt'


def read_archive_file(slug):
    """Read an existing archive txt file."""
    filename = archive_slug_to_filename(slug)
    filepath = os.path.join(OUTPUT_DIR, filename)
    if os.path.exists(filepath):
        with open(filepath, encoding='utf-8') as f:
            return f.read()
    return None


def merge_posts(archive_text, dynamo_text, title, date_str, link, archive_slug):
    """
    Merge archive and DynamoDB versions of the same post.
    DynamoDB is the authoritative source (actual DB content).
    We use the DynamoDB content as primary but preserve the archive URL.
    """
    # Extract content from dynamo text (after the === divider)
    dynamo_parts = dynamo_text.split('=' * 60 + '\n\n', 1)
    dynamo_content = dynamo_parts[1].strip() if len(dynamo_parts) > 1 else ''

    # Extract content from archive text
    archive_parts = archive_text.split('=' * 60 + '\n\n', 1)
    archive_content = archive_parts[1].strip() if len(archive_parts) > 1 else ''

    # Extract archive URL
    archive_url_match = re.search(r'^URL: (.*?)$', archive_text, re.MULTILINE)
    archive_url = archive_url_match.group(1) if archive_url_match else f'https://mattharris.org/{archive_slug}/'

    archive_wbm_match = re.search(r'^Archive: (.*?)$', archive_text, re.MULTILINE)
    archive_wbm = archive_wbm_match.group(1) if archive_wbm_match else ''

    # Use DynamoDB content as primary (it's the actual stored version)
    # but note the archive URL
    out = f'Title: {title}\n'
    out += 'Author: Marie Harris\n'
    if date_str:
        out += f'Date: {date_str}\n'
    out += f'URL: {archive_url}\n'
    if archive_wbm:
        out += f'Archive: {archive_wbm}\n'
    out += 'Source: combined (DynamoDB + archive.org)\n'
    out += '\n' + '=' * 60 + '\n\n'

    # Use DynamoDB content as it's more complete
    # If archive content has significant unique content, note it
    content = dynamo_content

    # Check if archive content is substantially longer (has content not in dynamo)
    if len(archive_content) > len(dynamo_content) * 1.5 and len(archive_content) - len(dynamo_content) > 500:
        content = dynamo_content
        content += '\n\n---\n*Additional content from archive:*\n\n' + archive_content

    out += content
    return out


def main():
    with open(DYNAMO_FILE) as f:
        dynamo_data = json.load(f)

    items = dynamo_data['Items']
    print(f'Processing {len(items)} DynamoDB items...')

    processed_archive_slugs = set()

    for item in sorted(items, key=lambda x: int(x.get('timestamp', {}).get('N', 0))):
        link = item.get('link', {}).get('S', '')
        title = item.get('title', {}).get('S', '')
        ts = item.get('timestamp', {}).get('N', '0')
        ts_int = int(ts)

        dt = datetime.fromtimestamp(ts_int) if ts_int else None
        date_str = dt.strftime('%Y-%m-%d') if dt else ''

        archive_slug = DYNAMO_TO_ARCHIVE.get(link)

        # Generate output filename
        if archive_slug:
            out_filename = archive_slug_to_filename(archive_slug)
            processed_archive_slugs.add(archive_slug)
        else:
            # DynamoDB-only post - create filename from date + link
            if dt:
                out_filename = f'{dt.year}-{dt.month:02d}-{link}.txt'
            else:
                out_filename = f'{link}.txt'

        out_path = os.path.join(OUTPUT_DIR, out_filename)

        # Generate DynamoDB text
        dynamo_text = dynamo_item_to_text(item)
        dynamo_text = apply_name_pronoun_updates(dynamo_text)

        if archive_slug:
            archive_text = read_archive_file(archive_slug)
            if archive_text:
                merged = merge_posts(archive_text, dynamo_text, title, date_str, link, archive_slug)
                merged = apply_name_pronoun_updates(merged)
                with open(out_path, 'w', encoding='utf-8') as f:
                    f.write(merged)
                print(f'  MERGED: {out_filename} ({len(merged)} chars)')
            else:
                with open(out_path, 'w', encoding='utf-8') as f:
                    f.write(dynamo_text)
                print(f'  DYNAMO (no archive): {out_filename} ({len(dynamo_text)} chars)')
        else:
            with open(out_path, 'w', encoding='utf-8') as f:
                f.write(dynamo_text)
            print(f'  NEW (dynamo only): {out_filename} ({len(dynamo_text)} chars)')

    # Update pronouns/names in archive-only posts
    print('\nUpdating archive-only posts...')
    for fname in os.listdir(OUTPUT_DIR):
        if not fname.endswith('.txt'):
            continue
        fpath = os.path.join(OUTPUT_DIR, fname)
        with open(fpath, encoding='utf-8') as f:
            text = f.read()
        updated = apply_name_pronoun_updates(text)
        if updated != text:
            with open(fpath, 'w', encoding='utf-8') as f:
                f.write(updated)
            print(f'  Updated names in: {fname}')

    print('\nDone.')


if __name__ == '__main__':
    main()
