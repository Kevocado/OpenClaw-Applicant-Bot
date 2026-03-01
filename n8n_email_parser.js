/**
 * n8n Code Node — Gmail "Application Received" Email Parser
 * 
 * Paste this into an n8n Code Node.
 * Input: Raw Gmail body text from a Gmail Trigger node.
 * Output: Structured JSON with Company, Role, and Location for Google Sheets append.
 */

// Get the raw email body from the previous Gmail Trigger node
const emailBody = $input.first().json.text || $input.first().json.body || "";
const emailSubject = $input.first().json.subject || "";

// ─── Regex Patterns ──────────────────────────────────────────────────────────
// These patterns match common "Thank you for applying" email formats from:
// LinkedIn, Handshake, Greenhouse, Lever, Workday, etc.

// Pattern 1: "Thank you for applying to/for [ROLE] at [COMPANY]"
const applyPattern1 = /(?:thank you for (?:your )?(?:application|applying|interest))\s+(?:to|for|at)\s+(?:the\s+)?(.+?)\s+(?:position|role|opportunity)?\s*(?:at|with)\s+(.+?)[\.\!\,\n]/i;

// Pattern 2: "[ROLE] at [COMPANY]" in subject line
const subjectPattern = /(.+?)\s+(?:at|with|-)\s+(.+)/i;

// Pattern 3: "application for [ROLE]" ... "at [COMPANY]"
const applyPattern2 = /application\s+(?:for|to)\s+(?:the\s+)?(.+?)(?:\s+at\s+|\s+with\s+)(.+?)[\.\!\,\n]/i;

// Pattern 4: "your application to [COMPANY]" with role mentioned separately
const companyOnlyPattern = /(?:application|applying)\s+(?:to|at|with)\s+(.+?)[\.\!\,\n]/i;
const rolePattern = /(?:position|role|opening)(?:\s*:\s*|\s+(?:of|for)\s+)(.+?)[\.\!\,\n]/i;

// Location patterns
const locationPatterns = [
    /(?:location|office|based in|located in)(?:\s*:\s*|\s+)([A-Za-z\s]+,\s*[A-Z]{2})/i,
    /(?:location|office|based in|located in)(?:\s*:\s*|\s+)([A-Za-z\s]+,\s*[A-Za-z\s]+)/i,
    /([A-Za-z\s]+,\s*[A-Z]{2})\s+(?:office|location|area)/i,
    /(?:remote|hybrid|on-site|onsite)/i,
];

// ─── Extraction Logic ────────────────────────────────────────────────────────

let company = "Unknown";
let role = "Unknown";
let location = "Not Specified";

// Try subject line first (most reliable)
const subjectMatch = emailSubject.match(subjectPattern);
if (subjectMatch) {
    role = subjectMatch[1].trim();
    company = subjectMatch[2].trim();
}

// Try email body patterns
if (company === "Unknown" || role === "Unknown") {
    const bodyMatch1 = emailBody.match(applyPattern1);
    if (bodyMatch1) {
        role = bodyMatch1[1].trim();
        company = bodyMatch1[2].trim();
    }
}

if (company === "Unknown" || role === "Unknown") {
    const bodyMatch2 = emailBody.match(applyPattern2);
    if (bodyMatch2) {
        role = bodyMatch2[1].trim();
        company = bodyMatch2[2].trim();
    }
}

// Fallback: extract company and role separately
if (company === "Unknown") {
    const companyMatch = emailBody.match(companyOnlyPattern);
    if (companyMatch) {
        company = companyMatch[1].trim();
    }
}

if (role === "Unknown") {
    const roleMatch = emailBody.match(rolePattern);
    if (roleMatch) {
        role = roleMatch[1].trim();
    }
}

// Extract location
for (const pattern of locationPatterns) {
    const locationMatch = emailBody.match(pattern);
    if (locationMatch) {
        location = locationMatch[1] ? locationMatch[1].trim() : locationMatch[0].trim();
        break;
    }
}

// ─── Clean Up ────────────────────────────────────────────────────────────────

// Remove trailing punctuation and common noise words
company = company.replace(/[.!,;:]+$/, "").replace(/\s+(team|inc|llc|corp)\.?$/i, " $1").trim();
role = role.replace(/[.!,;:]+$/, "").trim();

// Truncate overly long matches (likely a regex overshoot)
if (company.length > 100) company = company.substring(0, 100).trim();
if (role.length > 100) role = role.substring(0, 100).trim();

// ─── Output ──────────────────────────────────────────────────────────────────

return [{
    json: {
        Company: company,
        Role: role,
        Location: location,
        Source_Email_Subject: emailSubject.substring(0, 200),
        Parsed_At: new Date().toISOString(),
        Status: "Applied",
    }
}];
