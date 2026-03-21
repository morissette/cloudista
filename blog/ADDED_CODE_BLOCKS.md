# Added Code Blocks - Manual Review Log

These code blocks were added to posts that previously had none.
Review each to confirm accuracy before publishing.

---

## 2016-06-design-ha-cloud.txt
**Added:** 2 bash code blocks

### Block 1: AWS CLI recovery sequence
Location: After "...Now just a little finagling with my elastic IP and boom were back up."
Content: Commands to create snapshot, create volume from snapshot, stop instance,
detach/attach volumes, and reassociate Elastic IP.
**Review notes:** Instance IDs (i-91a71e55, i-yyyyyyyy) and volume IDs are placeholders
except for the original instance ID from the AWS retirement notice. Verify the
`--device /dev/xvda` path is correct for the original instance's root device.

### Block 2: CloudWatch alarm setup
Location: After the recovery sequence block.
Content: `aws cloudwatch put-metric-alarm` command for StatusCheckFailed metric.
**Review notes:** Uses the actual instance ID and account ID from the retirement email.
The SNS ARN (`arn:aws:sns:us-west-2:117905818048:NotifyMe`) is an example —
update with actual SNS topic ARN before publishing.

---

## 2015-12-bug-in-aws-console-s3.txt
**Added:** 1 bash code block (3 commands)

### Block 1: AWS CLI workaround for S3 metadata bug
Location: After the paragraph about the off-by-one bug speculation.
Content: Three `aws s3` commands showing how to correctly set Content-Encoding
metadata via CLI instead of the buggy console upload UI.
**Review notes:** Bucket name (`my-bucket`) and file paths are placeholders.
The `sync` command with `--metadata-directive REPLACE` may have side effects
on other metadata — verify this is the desired behavior before recommending to readers.

---

## Posts without code blocks (no addition needed - not technical)

- `2014-08-perl-tutorials-coming-soon.txt` — announcement post, no code appropriate
- `2014-08-scrum-point-cards-google-hangouts-extension.txt` — tool recommendation, no code appropriate
- `2016-07-amazons-machine-learning-engine-prime-music-horrible-non-existent.txt` — opinion piece, no code appropriate
