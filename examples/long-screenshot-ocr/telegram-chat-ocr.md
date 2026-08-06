**system**: Tuesday, August 4

**system**: This is a fictional conversation created for the Agent Vision Toolkit OCR demo.

**Maya Chen** (09:12): Good morning! This thread is for the Aurora beta launch review. Please keep every decision in the chat so the handoff stays searchable.

**You** (09:14): Morning. I will collect the final copy, QA status, release owner, and rollback notes here.

**Ethan Brooks** (09:16): Web dashboard build 0.9.7 is on staging. The empty-state illustration and export button are both fixed.

**Lena Ortiz** (09:18): Mobile QA is green on iOS 19. The Android keyboard still covers the last field on smaller screens.

> **Lena Ortiz**: The Android keyboard still covers the last field

**You** (09:20): Can we treat that as the only release blocker?

**Lena Ortiz** (09:21): Yes. Everything else is either passed or cosmetic.

**Noah Wilson** (09:24): I can patch the keyboard inset before lunch. I will post a new APK and the exact commit hash.

**Priya Shah** (09:27): Copy review is complete. Please use “Create workspace” instead of “Start workspace” in the onboarding button.

**You** (09:29): Confirmed. I updated the release checklist and tagged the string as final.

**Maya Chen** (09:33): For the launch email, the subject line should be: Aurora beta is ready for your team.

**Priya Shah** (09:35): And the preview text should be: Plan, review, and ship from one shared workspace.

**You** (09:38): Both lines are locked. No more copy changes after 16:00 today unless they fix a factual error.

**Ethan Brooks** (09:43): Staging health check:

status: ready
region: eu-west
build: 0.9.7
errors: 0

**Noah Wilson** (09:47): API latency is stable at 182 ms p95. The alert threshold remains 450 ms.

> **Noah Wilson**: API latency is stable at 182 ms p95

**You** (09:50): Great. Please add that number to the operations note.

**Noah Wilson** (09:52): Done. I also documented the rollback command and database backup timestamp.

**Maya Chen** (10:01): Who is the release owner during the first two hours?

**You** (10:03): I am the release owner from 14:00 to 16:00 UTC. Noah is the infrastructure backup.

**Noah Wilson** (10:04): Confirmed. I will stay in the incident channel during that window.

**Lena Ortiz** (10:11): Uploading the updated test matrix now.

aurora-beta-test-matrix.pdf 184 KB PDF

**You** (10:14): Received. The matrix has 46 passed cases, 1 blocked case, and 3 deferred accessibility checks.

**Priya Shah** (10:19): The accessibility checks must stay visible in the launch notes. Please do not hide them under “known issues.”

**You** (10:21): Agreed. I created a separate Accessibility follow-up section with an owner and due date.

**Maya Chen** (10:25): Perfect. Customer support also needs a one-paragraph summary before tomorrow morning.

**Ethan Brooks** (10:31): Small detail: the CSV export filename now uses the workspace name and UTC date, for example aurora-team_2026-08-04.csv.

**You** (10:34): That naming format is clear. Add one test for spaces and non-ASCII workspace names.

**Ethan Brooks** (10:36): Added. Spaces become hyphens, while Unicode letters remain unchanged.

**system**: Wednesday, August 5

**Noah Wilson** (08:42): Morning update: the nightly backup completed at 02:15 UTC and restore verification passed.

**Lena Ortiz** (08:46): Android build 0.9.8 is ready. The keyboard inset issue is fixed on 360 px, 390 px, and 412 px widths.

> **Lena Ortiz**: The keyboard inset issue is fixed

**You** (08:48): Excellent. Please rerun onboarding, invite flow, and billing settings before we clear the blocker.

**Lena Ortiz** (09:17): Retest complete:
• Onboarding: passed
• Invite flow: passed
• Billing settings: passed
• Screen rotation: passed

**You** (09:19): Release blocker cleared. Marking mobile QA as green.

**Maya Chen** (09:23): The support summary is approved: Aurora beta gives teams one place to plan work, review decisions, and prepare releases.

**Priya Shah** (09:26): Please preserve the serial comma in “plan work, review decisions, and prepare releases.”

**You** (09:28): Confirmed. The approved sentence is copied verbatim into the support brief.

**Ethan Brooks** (09:41): Production build is compiling now. Expected artifact time is 10:05 UTC.

**Noah Wilson** (09:44): Monitoring dashboard is open. Error rate, latency, queue depth, and login failures are pinned.

**You** (09:47): Before release, confirm these four values:
1. Error rate below 1%
2. p95 latency below 450 ms
3. Queue depth below 500
4. Login failures below 20 per minute

**Noah Wilson** (09:50): Confirmed. Current values are 0.12%, 176 ms, 43 jobs, and 2 login failures per minute.

**Ethan Brooks** (10:06): Production artifact is ready.

artifact: aurora-web-1.0.0
sha256: 8f2c4d71b6a9
created: 2026-08-05 10:05 UTC

**You** (10:08): Checksum recorded. Start the deployment at 10:15 UTC.

**Maya Chen** (10:10): Launch email is scheduled for 10:45 UTC, thirty minutes after deployment begins.

**Priya Shah** (10:12): Help center article is published but unlisted. We will make it public after the health check.

**You** (10:15): Deployment started.

**Noah Wilson** (10:22): 25% complete. Metrics are normal and there are no new application errors.

**Noah Wilson** (10:29): 75% complete. One cache node restarted automatically; traffic was unaffected.

**You** (10:34): Deployment complete. Beginning the fifteen-minute health check now.

**Lena Ortiz** (10:38): Smoke test passed on web, iOS, and Android. Login, workspace creation, invite, and export all work.

**Noah Wilson** (10:49): Health check passed. Error rate is 0.09% and p95 latency is 188 ms.

**You** (10:51): Aurora 1.0 is officially live. Thank you, everyone!

**Maya Chen** (10:53): Launch email sent. I will post engagement numbers in this thread tomorrow.

**Priya Shah** (10:55): Help center article is public, and the support team has the approved response template.

**You** (10:58): Final handoff:
• Release owner: You
• Infrastructure backup: Noah Wilson
• QA owner: Lena Ortiz
• Copy owner: Priya Shah
• Product owner: Maya Chen
• Engineering owner: Ethan Brooks

**system**: Maya Chen pinned “Aurora 1.0 is officially live.”
