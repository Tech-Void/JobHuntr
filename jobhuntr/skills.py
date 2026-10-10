"""IT / security skill vocabulary, used to compare a resume against job descriptions.

Each entry is (display name, group, regex). Regexes are matched case-insensitively against plain text.
"""
import re

_SKILLS = [
    # Operating systems & endpoints
    ("Windows Server", "Systems", r"windows server|server 20(?:1[269]|22|25)"),
    ("Windows 10/11", "Systems", r"windows (?:10|11)|windows desktop|windows os"),
    ("Linux", "Systems", r"\blinux\b|\bunix\b|\brhel\b|red hat|ubuntu|centos"),
    ("macOS", "Systems", r"mac ?os|\bapple\b|\bjamf\b"),
    ("Active Directory", "Systems", r"active directory|\bad ds\b|\bad\b(?= (?:user|account|group))"),
    ("Group Policy", "Systems", r"group policy|\bgpo"),
    ("Entra ID / Azure AD", "Systems", r"entra|azure ad|azure active directory"),
    ("Microsoft 365", "Systems", r"microsoft 365|office 365|\bm365\b|\bo365\b"),
    ("Exchange", "Systems", r"\bexchange\b"),
    ("SharePoint", "Systems", r"sharepoint"),
    ("Intune", "Systems", r"\bintune\b|endpoint manager"),
    ("SCCM / MECM", "Systems", r"\bsccm\b|\bmecm\b|configuration manager"),
    ("Imaging / deployment", "Systems", r"imaging|autopilot|\bmdt\b|\bwds\b|reimag"),
    ("VMware", "Systems", r"vmware|vsphere|esxi|vcenter"),
    ("Hyper-V", "Systems", r"hyper-?v"),
    ("Citrix / VDI", "Systems", r"citrix|\bvdi\b|virtual desktop"),
    ("Backup & recovery", "Systems", r"\bbackups?\b|veeam|disaster recovery|\bbcdr\b|commvault|rubrik"),
    ("SQL Server", "Systems", r"sql server|\bmssql\b"),
    ("Oracle DB", "Systems", r"oracle (?:database|db)|\bpl/sql"),
    ("Hardware troubleshooting", "Support", r"hardware (?:troubleshoot|repair|support)|troubleshoot\w* hardware|peripherals?|printers?"),
    ("Help desk / ticketing", "Support", r"help ?desk|service desk|ticketing|ticket queue|tier [12i]|\bincidents? tickets?"),
    ("ServiceNow", "Support", r"servicenow"),
    ("Remedy / Jira", "Support", r"\bremedy\b|\bjira\b"),
    ("ITIL", "Support", r"\bitil\b"),
    ("Customer service", "Support", r"customer service|end[- ]users?|user support"),
    ("Mobile devices / MDM", "Support", r"mobile device|\bmdm\b|iphones?|android devices"),
    # Networking
    ("TCP/IP", "Networking", r"tcp/?ip|\bosi model\b|subnet"),
    ("DNS / DHCP", "Networking", r"\bdns\b|\bdhcp\b"),
    ("Routing & switching", "Networking", r"routing|switching|\bvlans?\b|\bospf\b|\bbgp\b|\beigrp\b|spanning tree"),
    ("Cisco", "Networking", r"\bcisco\b|\bios-?xe\b|\bnx-?os\b"),
    ("Firewalls", "Networking", r"firewalls?|palo alto|fortinet|fortigate|\basa\b|checkpoint|check point"),
    ("VPN", "Networking", r"\bvpns?\b|anyconnect|globalprotect"),
    ("Wireless", "Networking", r"wireless|wi-?fi|\bwlan\b|meraki|aruba"),
    ("Load balancers", "Networking", r"load balanc|\bf5\b|big-?ip"),
    ("Network monitoring", "Networking", r"solarwinds|nagios|prtg|zabbix|network monitoring|\bsnmp\b"),
    ("Packet analysis", "Networking", r"wireshark|tcpdump|packet (?:capture|analysis)"),
    ("VoIP / telephony", "Networking", r"\bvoip\b|telephony|call manager|\bcucm\b"),
    # Security operations
    ("SIEM", "Security", r"\bsiem\b|log (?:analysis|correlation)"),
    ("Splunk", "Security", r"splunk"),
    ("Microsoft Sentinel", "Security", r"sentinel"),
    ("QRadar / Elastic", "Security", r"qradar|elastic(?:search)?|\belk\b"),
    ("EDR / XDR", "Security", r"\bedr\b|\bxdr\b|crowdstrike|carbon black|sentinelone|defender for endpoint|endpoint detection"),
    ("Vulnerability management", "Security", r"vulnerabilit(?:y|ies) (?:management|scan|assess)|nessus|tenable|qualys|\bacas\b|rapid7"),
    ("Incident response", "Security", r"incident (?:response|handling)|\bir\b(?= (?:team|plan|process))"),
    ("Threat hunting / intel", "Security", r"threat (?:hunt|intel)|\bioc\b|indicators of compromise|mitre att&?ck"),
    ("SOC operations", "Security", r"\bsoc\b|security operations center"),
    ("Penetration testing", "Security", r"penetration test|pen ?test|red team|metasploit|burp suite|\bkali\b"),
    ("Nmap / scanning", "Security", r"\bnmap\b|port scan"),
    ("IAM / access control", "Security", r"identity and access|\biam\b|access control|least privilege|role-based access|\brbac\b|provisioning"),
    ("PAM / CyberArk", "Security", r"\bpam\b|privileged access|cyberark|beyondtrust"),
    ("MFA / SSO", "Security", r"\bmfa\b|multi-?factor|\bsso\b|single sign-on|okta|\bsaml\b|duo"),
    ("PKI / encryption", "Security", r"\bpki\b|certificates?(?= (?:management|authority))|encryption|\btls\b|\bssl\b"),
    ("Email security / phishing", "Security", r"phishing|email security|proofpoint|mimecast"),
    ("Malware analysis", "Security", r"malware analysis|reverse engineer|sandbox(?:ing)?"),
    ("Digital forensics", "Security", r"forensic|\bdfir\b|encase|\bftk\b|autopsy|volatility|chain of custody|e-?discovery"),
    ("Data loss prevention", "Security", r"\bdlp\b|data loss prevention"),
    # Compliance & frameworks
    ("NIST / RMF", "Compliance", r"\bnist\b|\brmf\b|800-53|800-171|risk management framework"),
    ("STIGs / hardening", "Compliance", r"\bstigs?\b|hardening|\bcis benchmark|scap"),
    ("DoD 8140 / 8570", "Compliance", r"\b8140\b|\b8570\b|\biat\b|\biam level"),
    ("ATO / A&A", "Compliance", r"\bato\b|authority to operate|assessment and authorization|\bemass\b|\bpoa&?m\b"),
    ("HIPAA", "Compliance", r"\bhipaa\b|\bphi\b"),
    ("PCI / SOX", "Compliance", r"\bpci\b|\bsox\b|sarbanes"),
    ("ISO 27001 / SOC 2", "Compliance", r"iso 27001|soc 2|soc2"),
    ("FedRAMP / CMMC", "Compliance", r"fedramp|\bcmmc\b"),
    ("Risk assessment / audit", "Compliance", r"risk assessment|security audit|audit(?:ing)? (?:controls|logs)|\bgrc\b"),
    # Cloud & automation
    ("AWS", "Cloud & code", r"\baws\b|amazon web services|\bec2\b|\bs3\b"),
    ("Azure", "Cloud & code", r"\bazure\b"),
    ("Google Cloud", "Cloud & code", r"\bgcp\b|google cloud"),
    ("Terraform / IaC", "Cloud & code", r"terraform|infrastructure as code|\biac\b|ansible|cloudformation"),
    ("Docker / Kubernetes", "Cloud & code", r"docker|kubernetes|\bk8s\b|containers?\b"),
    ("CI/CD / DevOps", "Cloud & code", r"\bci/?cd\b|devops|devsecops|jenkins|gitlab|github actions|azure devops"),
    ("Git", "Cloud & code", r"\bgit\b|github|gitlab|bitbucket"),
    ("PowerShell", "Cloud & code", r"powershell"),
    ("Python", "Cloud & code", r"\bpython\b"),
    ("Bash / shell scripting", "Cloud & code", r"\bbash\b|(?<!power)shell script"),
    ("SQL", "Cloud & code", r"\bsql\b"),
    ("JavaScript / web", "Cloud & code", r"javascript|typescript|\bhtml\b|\bcss\b|react\b|node\.?js"),
    ("Java / C#", "Cloud & code", r"\bjava\b|\bc#|\.net\b"),
    ("REST APIs", "Cloud & code", r"rest(?:ful)? api|\bapis?\b"),
    # Healthcare IT
    ("Epic", "Healthcare IT", r"\bepic\b"),
    ("Cerner / Oracle Health", "Healthcare IT", r"cerner|oracle health"),
    ("HL7 / interfaces", "Healthcare IT", r"\bhl7\b|\bfhir\b|interface engine"),
    ("Biomedical equipment", "Healthcare IT", r"biomedical|medical equipment|medical devices?"),
    # Professional
    ("Documentation / SOPs", "Professional", r"documentation|standard operating procedures|\bsops?\b|knowledge base"),
    ("Project coordination", "Professional", r"project (?:management|coordination)|\bpmp\b|agile|scrum"),
    ("Training users", "Professional", r"train(?:ing)? (?:end )?users|user training"),
]

SKILLS = [(name, group, re.compile(pat, re.I)) for name, group, pat in _SKILLS]
GROUPS = {name: group for name, group, _ in SKILLS}


def find_skills(text: str) -> list:
    """Names of every vocabulary skill mentioned in the text."""
    text = text or ""
    return [name for name, _, pat in SKILLS if pat.search(text)]


def match(job_skills, resume_skills):
    """Score how well a resume covers the skills a job mentions.

    Returns None when the job lists too few recognizable skills to judge, else
    {"score": 0-100, "have": [...], "missing": [...]}.
    """
    job_skills = list(dict.fromkeys(job_skills or []))
    if len(job_skills) < 3:
        return None
    mine = set(resume_skills or [])
    have = [s for s in job_skills if s in mine]
    missing = [s for s in job_skills if s not in mine]
    # (have+1)/(total+2): a posting naming only 3 skills can't score a confident 100%
    score = round(100 * (len(have) + 1) / (len(job_skills) + 2))
    return {"score": score, "have": have, "missing": missing}
