# Disclaimer

## Unofficial Community Project

**PrintFilamentTracker is an independent, community-developed project and is NOT affiliated with, endorsed by, or sponsored by Bambu Lab Co., Ltd.**

This software was created for personal, non-commercial use. It is distributed under the [PolyForm Noncommercial License 1.0.0](LICENSE).

---

## Trademark Notice

"Bambu", "Bambu Lab", and associated logos are registered trademarks of Bambu Lab Co., Ltd. These names are used solely for the purpose of identifying the third-party services that this software integrates with, and do not imply any endorsement, sponsorship, or affiliation.

---

## Unofficial API Usage & Terms of Service Risk

PrintFilamentTracker accesses Bambu Lab cloud services through endpoints that are **not part of any official, publicly documented API**. These endpoints were discovered through community research and may change or be discontinued at any time without notice.

### Authorization Control System (January 2025)

In January 2025, Bambu Lab introduced an **Authorization Control System** via firmware update (version 01.08.03.00, announced January 16, 2025). This system enforces authorization requirements for certain critical printer operations in both LAN and Cloud modes. Note that not all API access is blocked — status monitoring, MQTT, and SD-card printing remain unaffected per the official announcement; only specific critical operations require authorization.

Affected critical operations include: initiating print jobs, controlling the motion system, temperature, fans, AMS settings, and calibrations. Known affected third-party tools include OrcaSlicer (network plugin), Home Assistant integrations, and various third-party accessories.

**PrintFilamentTracker accesses Bambu Cloud via unofficial API endpoints and may be affected by future enforcement of this system.** Bambu Lab may extend these controls to additional operations without notice.

---

### Directly Relevant Clauses from Bambu Lab's Terms of Use

The following clauses from [Bambu Lab's Terms of Use](https://bambulab.com/en-us/policies/terms) (last updated: **April 24, 2024**) are directly applicable to the use of this software:

**Section 3.1 — Third-Party Software Restriction**
> *"You may not use Bambu Lab technology or Bambu Lab intellectual property to develop software or design, develop, manufacture, sell, or licence third-party devices/accessories associated with Bambu Lab Product without Bambu Lab's prior consent."*

**Section 3.4 — Prohibition on Reverse Engineering**
> *"Except as otherwise expressly permitted, you shall not, nor allow any other person to misappropriate, intrude or make other inappropriate use of the Product, including, but not limited to modify, discoder, copy, reverse engineer, publish, publicly disseminate, decompile, export codes, disassemble or create derivatives of the Product in any way."*

**Section 3.5(1) — Scope of Use**
> *"[You agree not to] copy or use any part of the Software beyond the scope of these Terms."*

**Section 3.5(5) — DRM Bypass Prohibition**
> *"[You agree not to] attempt to destroy, bypass, change, invalidate or escape from the Product and/or any digital rights management system that is part of the organic composition of the Product."*

**Section 11.1 — Account Termination**
> *"BREACH OF YOUR OBLIGATIONS WITH ANY TERMS OR CONDITIONS OF THESE TERMS MAY RESULT IN THE DEACTIVATION OF YOUR ACCOUNT AND LOSS OR RESTRICTION OF ACCESS TO THE CONTENT ASSOCIATED WITH THE PRODUCT."*

### Risk Summary

| Risk | Description |
|------|-------------|
| **ToS Violation (§3.1)** | Using Bambu Lab technology to build third-party software without prior consent is expressly prohibited |
| **Reverse Engineering (§3.4)** | The unofficial API endpoints were discovered through community reverse research |
| **Account Suspension (§11.1)** | Bambu Lab may deactivate your Bambu account if a violation is determined |
| **API Instability** | These endpoints may be changed, restricted, or discontinued at any time |
| **Authorization Control (2025)** | Bambu Lab's Authorization Control System (firmware Jan 2025) enforces authorization for critical print operations in both LAN and Cloud modes; PrintFilamentTracker may be affected if Bambu Lab extends controls to the Cloud API endpoints it uses |
| **Legal Action** | While no known legal action against individual users has occurred to date, Bambu Lab reserves the right to pursue remedies under their ToS |

**By using this software, you acknowledge that you have read, understood, and accepted all of the above risks. You are solely responsible for any legal, account-related, or service consequences arising from use of this software.**

---

## Contributor Notice

By contributing to this project, you agree that:

1. Your contributions are your own original work.
2. You grant the project maintainer a non-exclusive license to use, modify, and distribute your contributions under the terms of the [PolyForm Noncommercial License 1.0.0](LICENSE).
3. You understand and accept the third-party API risks described above.
4. You will not contribute any code that is directly copied from Bambu Lab's proprietary software or reverse-engineered binaries.

---

## Credential Security

Your Bambu Lab account credentials (username, password, access token) are processed **locally on your machine only**:

- Passwords are **never stored** — only the time-limited authentication token is saved to the local SQLite database.
- The token is stored in plain text in `data/tracker.db`. Protect this file accordingly.
- You are responsible for securing access to the machine and database file.

---

## No Warranty

This software is provided "as is", without warranty of any kind. The authors are not responsible for any damage, data loss, account suspension, or legal consequences arising from the use of this software.

See the [LICENSE](LICENSE) file for full terms.
