"""CLI Terminal Testing Interface for Generic Daily Report Generation.

This script allows testing daily report extraction and PDF/DOCX generation
directly from the terminal console using text input or audio files.
It does NOT invoke any WhatsApp messaging APIs.
"""

import sys
import os
import argparse
import asyncio
import logging

# Ensure parent directory is in sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

# Ensure UTF-8 output encoding for Windows terminal compatibility
if sys.stdout.encoding != 'utf-8':
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:
        pass

from app.ai.provider import AIProvider
from app.core.config import settings
from app.reports.generator import DocxReportGenerator


def setup_cli_logging():
    """Configures clean, human-readable console logging for CLI mode."""
    logging.basicConfig(
        level=logging.INFO if not settings.app.debug else logging.DEBUG,
        format="%(asctime)s [%(levelname)s] %(name)s - %(message)s",
        datefmt="%H:%M:%S",
    )


async def main():
    parser = argparse.ArgumentParser(
        description="Generic Daily Report Generator CLI — Local Terminal Test Runner"
    )
    parser.add_argument(
        "-t", "--text", type=str, help="Text input update describing tasks, metrics, or domain progress."
    )
    parser.add_argument(
        "-f", "--file", type=str, help="Path to a text file (.txt) containing the update transcript."
    )
    parser.add_argument(
        "-a", "--audio", type=str, help="Path to a voice note audio file (.m4a, .ogg, .mp3, .wav)."
    )
    parser.add_argument(
        "-p", "--photos", nargs="*", default=[], help="Paths to site/progress photographs (.jpg, .png)."
    )
    parser.add_argument(
        "--format", choices=["pdf", "docx", "both"], default="pdf", help="Output format (default: pdf)."
    )

    args = parser.parse_args()
    setup_cli_logging()

    print("\n" + "=" * 70)
    print(" 🚀 GENERIC DAILY REPORT GENERATOR — LOCAL TERMINAL TESTER")
    print("=" * 70)

    # 1. Gather text update
    text_content = ""
    if args.text:
        text_content = args.text
    elif args.file:
        if os.path.exists(args.file):
            with open(args.file, "r", encoding="utf-8") as f:
                text_content = f.read()
        else:
            print(f"❌ Error: Text file not found at '{args.file}'")
            return

    # 2. Build the AI provider from the configured LLM_* / STT_* settings.
    ai_provider = AIProvider()
    described = ai_provider.describe()
    print(f"🤖 Chat: {described['chat']['label']} / {described['chat']['model']}")
    print(f"🎤 STT:  {described['stt']['label']} / {described['stt']['model']}")

    if not described["chat"]["configured"]:
        print("\n⚠️ No API key for the chat provider — reports will use the rule-based fallback.")
        print("   Set LLM_PROVIDER, LLM_MODEL and LLM_API_KEY in .env (see .env.example).")
    if args.audio and not described["stt"]["configured"]:
        print("\n❌ No API key for the speech-to-text provider; cannot transcribe audio.")
        print("   Set STT_PROVIDER, STT_MODEL and STT_API_KEY in .env, or use a free option:")
        print('   STT_PROVIDER="groq" STT_MODEL="whisper-large-v3"')
        return

    # 3. Handle Audio file if provided
    if args.audio:
        if not os.path.exists(args.audio):
            print(f"❌ Error: Audio file not found at '{args.audio}'")
            return
        
        print(f"\n🎤 Processing Audio File: '{args.audio}'...")
        print("⏳ Running Speech-to-Text Transcription...")
        transcript = await ai_provider.transcribe_audio_only(args.audio)
        print("\n" + "-" * 50)
        print("📝 RAW AUDIO TRANSCRIPT:")
        print("-" * 50)
        print(transcript if transcript else "(Empty transcript)")
        print("-" * 50)

        if text_content:
            text_content = f"{transcript}\n\nAdditional Text: {text_content}"
        else:
            text_content = transcript

    if not text_content or not text_content.strip():
        print("\n❌ Error: No input provided. Please specify --text, --file, or --audio.")
        print("\nExample usage:")
        print('  python scripts/cli_test.py --text "Software team completed auth endpoints and fixed 2 bugs in payment service."')
        print('  python scripts/cli_test.py --audio "path/to/voice_note.m4a"')
        return

    print("\n" + "-" * 50)
    print("📥 INPUT UPDATE SENT TO AI:")
    print("-" * 50)
    print(text_content.strip())
    print("-" * 50)

    # 4. Perform AI Analysis & Extraction
    print("\n⚙️ Extracting & structuring report data using AI...")
    extracted_report = await ai_provider.extract_from_text(text_content)
    draft_dict = extracted_report.model_dump()

    # 5. Display Structured Report in Terminal Console
    print("\n" + "=" * 70)
    print(" 📊 GENERATED REPORT DRAFT PREVIEW (TERMINAL OUTPUT)")
    print("=" * 70)

    rpt = extracted_report.report
    meta = rpt.metadata if rpt else None

    print(f"📌 Context / Project: {extracted_report.site_name or (meta.project_name if meta else 'N/A')}")
    print(f"📍 Location / Module: {meta.location if meta else 'N/A'}")
    print(f"👤 Prepared By:       {meta.prepared_by if meta else 'N/A'}")
    print(f"📅 Date:              {extracted_report.report_date or 'Today'}")
    print("\n📝 EXECUTIVE SUMMARY:")
    print(f"   {extracted_report.summary or 'N/A'}")

    print("\n✅ WORK / TASKS COMPLETED:")
    if rpt and rpt.work_summaries:
        for idx, item in enumerate(rpt.work_summaries, 1):
            pct_str = f" ({item.progress_percentage}%)" if item.progress_percentage is not None else ""
            print(f"   {idx}. [{item.status}] [{item.area}] {item.activity}{pct_str}")
    elif extracted_report.tasks:
        for idx, t in enumerate(extracted_report.tasks, 1):
            print(f"   {idx}. {t}")
    else:
        print("   (No work summary items mentioned)")

    print("\n🛠️ RESOURCES USED:")
    if rpt and rpt.resources:
        for idx, res in enumerate(rpt.resources, 1):
            print(f"   {idx}. [{res.resource_type}] {res.description} (Qty: {res.quantity or 'N/A'})")
    else:
        print("   (No resource data mentioned)")

    print("\n⚠️ ISSUES / BLOCKERS:")
    if rpt and rpt.issues:
        for idx, iss in enumerate(rpt.issues, 1):
            print(f"   {idx}. {iss.issue} | Impact: {iss.impact or 'N/A'} | Action: {iss.action_taken or 'N/A'}")
    elif extracted_report.important_points:
        for idx, pt in enumerate(extracted_report.important_points, 1):
            print(f"   {idx}. {pt}")
    else:
        print("   (No issues or blockers reported)")

    print("\n🎯 PLAN FOR NEXT DAY:")
    if rpt and rpt.next_day_plan:
        for idx, plan in enumerate(rpt.next_day_plan, 1):
            print(f"   {idx}. [{plan.area}] {plan.planned_activity} (Target: {plan.target_completion or 'N/A'})")
    else:
        print("   (No next day plans mentioned)")

    print("\n" + "=" * 70)

    # 6. Generate PDF/DOCX file output
    generator = DocxReportGenerator()
    sender_id = "CLI_USER"
    photo_paths = [p for p in args.photos if os.path.exists(p)]

    if args.format in ("pdf", "both"):
        print("\n📄 Compiling PDF Document...")
        pdf_file = generator.generate_report_by_format(
            sender_id=sender_id,
            draft=draft_dict,
            photo_paths=photo_paths,
            output_format="pdf",
        )
        print(f"✅ PDF Report generated at: {os.path.abspath(pdf_file)}")

    if args.format in ("docx", "both"):
        print("\n📘 Compiling DOCX Word Document...")
        docx_file = generator.generate_report_by_format(
            sender_id=sender_id,
            draft=draft_dict,
            photo_paths=photo_paths,
            output_format="docx",
        )
        print(f"✅ DOCX Report generated at: {os.path.abspath(docx_file)}")

    print("\n✨ Report Generation Completed Successfully!\n")


if __name__ == "__main__":
    asyncio.run(main())
