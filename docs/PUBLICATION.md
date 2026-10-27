# Source publication

This repository publishes the tracked application source from the private Azure build at commit `d77e1e547d58233e4c3090beee6408a94ddc04cb` on 27 October 2026. The public repository begins with a source snapshot rather than importing private operational Git history. It is the original application code, not a reconstruction.

Publication preparation replaced the deployment-specific README with public setup instructions, removed the server address from that README, expanded ignore rules and added this provenance document. A portability fix makes the H-MEM adapter find Node through explicit configuration, SIGNALDESK_NODE, or PATH before falling back to the original Azure location. This public-copy change has not been deployed to Azure. Original deployment paths remain in service templates and operational scripts and require adaptation on other hosts.

## Evidence boundaries

The private build reports 38 baseline application tests, four subsequent event-conflict regression tests, ten upstream H-MEM tests and 25 deployment checks passing. Its latest independent review passed within explicitly disclosed external setup limitations. These are prior deployment results, not claims that the public checkout reproduced all deployment/browser tests.

Gmail tests used a local fake provider. Zetaris and Nightshift/Nemotron were checked as adapter contracts, not as live integrations. No live send, successful real introduction, revenue outcome or full-register investigation is claimed.

Private database files, register/job/event exports, real client records, messages, passwords, encryption keys, OAuth secrets, environment files, logs, screenshots and private build-control files are not part of this publication. Synthetic example contacts use reserved example domains.

Existing EUJobs code and services were not changed by this publication. This repository does not include EUJobs source or its data; its importer reads authorised source data into its own database.

## Public-copy verification

On 27 October 2026, the documented portable test command passed **40 tests**, skipped **one** private EUJobs-source test, and deselected **one** Azure-specific browser test. A fresh empty workspace also passed health, login, unauthenticated API protection and an actual local H-MEM probe. No external provider calls or emails were made. These results do not replace the outstanding live Gmail, Zetaris or Nemotron validation.
