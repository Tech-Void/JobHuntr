"""Optional AI helper: tailor application materials to one posting with the Claude API.

Uses the user's own Anthropic API key (entered in Settings). Nothing is sent anywhere unless they click a button.
"""
MODEL = "claude-opus-5-5"

SYSTEM = (
    "You help a job seeker apply to a specific posting. "
    "Use only facts from their resume and profile; never invent experience, employers, dates, degrees or "
    "certifications. If the resume lacks something the posting wants, say how to address it honestly "
    "(e.g. 'currently studying for <certification>'). Write in plain, confident, specific language with no clichés. "
    "Output Markdown."
)

TASKS = {
    "cover_letter": (
        "Write a cover letter (250-350 words) for this posting. Open with why this specific role and employer, "
        "connect 2-3 concrete items from the resume to the posting's requirements, and close with a short call to "
        "action. Use [Hiring Manager] if no name is given."
    ),
    "bullets": (
        "Rewrite or add 4-6 resume bullet points that best match this posting, using only real experience from the "
        "resume. Start each with a strong verb and keep each under 25 words. After the bullets, list the posting's "
        "top keywords that should appear somewhere in the resume."
    ),
    "interview": (
        "Prepare me for an interview for this posting: 6 likely questions (mix of technical and behavioral) with "
        "a short note on how I could answer each from my resume, then 3 smart questions I should ask them."
    ),
}


class AIError(RuntimeError):
    pass


def tailor(api_key: str, task: str, resume_text: str, extra: str, job: dict, description: str) -> str:
    if not api_key:
        raise AIError("Add your Anthropic API key in Settings to use AI tailoring")
    if task not in TASKS:
        raise AIError(f"Unknown task {task}")
    if not resume_text.strip():
        raise AIError("Add your resume on the 'My resume' page first")

    prompt = (
        f"<resume>\n{resume_text}\n</resume>\n\n"
        f"<extra_profile>{extra or 'none'}</extra_profile>\n\n"
        f"<posting>\nTitle: {job['title']}\nEmployer: {job['company']}\nLocation: {job['location']}\n\n"
        f"{description or '(description unavailable)'}\n</posting>\n\n{TASKS[task]}"
    )
    import anthropic  # imported on first use so the app starts quickly

    client = anthropic.Anthropic(api_key=api_key, timeout=180.0, max_retries=2)
    try:
        response = client.beta.messages.create(
            model=MODEL,
            max_tokens=16000,
            system=SYSTEM,
            output_config={"effort": "medium"},
            betas=["server-side-fallback-2026-07-01"],
            fallbacks="default",
            messages=[{"role": "user", "content": prompt}],
        )
    except anthropic.AuthenticationError:
        raise AIError("Your Anthropic API key was rejected. Check it in Settings.")
    except anthropic.PermissionDeniedError:
        raise AIError("Your API key doesn't have access to this model.")
    except anthropic.RateLimitError:
        raise AIError("Rate limited by the Anthropic API. Wait a minute and try again.")
    except anthropic.BadRequestError as e:
        raise AIError(f"The API rejected the request: {e.message}")
    except anthropic.APIStatusError as e:
        raise AIError(f"Anthropic API error ({e.status_code}). Try again shortly.")
    except anthropic.APIConnectionError:
        raise AIError("Couldn't reach the Anthropic API. Check your internet connection.")

    if response.stop_reason == "refusal":
        raise AIError("The model declined this request.")
    text = "".join(block.text for block in response.content if block.type == "text").strip()
    if not text:
        raise AIError("The model returned an empty response. Try again.")
    if response.stop_reason == "max_tokens":
        text += "\n\n*(cut off - try again)*"
    return text
