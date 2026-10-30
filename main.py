"""PortaLoop: console-based laptop lending tracker."""

from __future__ import annotations

import json
import os
import re
import shutil
import sys
from datetime import date, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent
DATA_FILE = ROOT / "prestamos.json"
EVIDENCE_DIR = ROOT / "evidencias"
TODAY = date.today


def enable_terminal_colors() -> bool:
    """Enable ANSI colors where supported, with no third-party dependencies."""
    if not sys.stdout.isatty():
        return False
    if os.name == "nt":
        try:
            import ctypes

            handle = ctypes.windll.kernel32.GetStdHandle(-11)
            mode = ctypes.c_uint()
            if ctypes.windll.kernel32.GetConsoleMode(handle, ctypes.byref(mode)):
                ctypes.windll.kernel32.SetConsoleMode(handle, mode.value | 0x0004)
        except (AttributeError, OSError):
            pass
    return True


USE_COLOR = enable_terminal_colors()
RESET = "\033[0m" if USE_COLOR else ""
BOLD = "\033[1m" if USE_COLOR else ""
CYAN = "\033[96m" if USE_COLOR else ""
GREEN = "\033[92m" if USE_COLOR else ""
YELLOW = "\033[93m" if USE_COLOR else ""
RED = "\033[91m" if USE_COLOR else ""
BG_NAVY = "\033[48;5;17m" if USE_COLOR else ""
BG_PANEL = "\033[48;5;24m" if USE_COLOR else ""
BG_TEAL = "\033[48;5;30m" if USE_COLOR else ""
FG_WHITE = "\033[97m" if USE_COLOR else ""
FG_MUTED = "\033[38;5;159m" if USE_COLOR else ""


def print_message(message: str, kind: str = "info") -> None:
    color = {"success": GREEN, "warning": YELLOW, "error": RED, "info": CYAN}.get(kind, "")
    marker = {"success": "✓", "warning": "!", "error": "✗", "info": "›"}.get(kind, "›")
    print(f"{color}{marker} {message}{RESET}")


def draw_menu(state: dict) -> None:
    columns = shutil.get_terminal_size((80, 24)).columns
    width = max(72, min(100, columns - 2))
    inner = width - 2
    double_column = width >= 76

    def border(left: str, fill: str, right: str, background: str = "") -> None:
        print(f"{background}{CYAN}{left}{fill * inner}{right}{RESET}")

    def line(text: str = "", centered: bool = False, background: str = "", foreground: str = "") -> None:
        content_width = inner - 2
        text = text[:content_width]
        content = text.center(content_width) if centered else text.ljust(content_width)
        print(f"{background}{CYAN}║{RESET}{background} {foreground}{content}{RESET}{background} {CYAN}║{RESET}")

    open_loans = pending_loans(state)
    open_codes = {loan["equipment_code"] for loan in open_loans}
    available_count = sum(
        item.get("active", True) and item["code"] not in open_codes
        for item in state["equipment"]
    )
    overdue_count = sum(loan["due_date"] < TODAY().isoformat() for loan in open_loans)

    print()
    border("╔", "═", "╗", BG_NAVY)
    line("◈  PORTALOOP  ◈", centered=True, background=BG_NAVY, foreground=FG_WHITE + BOLD)
    line("LAPTOP LENDING  •  SHARED WITH CARE", centered=True, background=BG_NAVY, foreground=FG_MUTED)
    border("╠", "═", "╣", BG_PANEL)
    # Compact KPI labels keep all five counts on one line in a standard terminal.
    if width >= 94:
        score = (
            f"💻 LAPTOPS {len(state['equipment'])}  │  ✅ AVAILABLE {available_count}  │  "
            f"👥 BORROWERS {len(state['borrowers'])}  │  🔄 OPEN {len(open_loans)}  │  "
            f"⚠️ OVERDUE {overdue_count}"
        )
    else:
        score = (
            f"💻 LAP {len(state['equipment'])} │ ✅ FREE {available_count} │ "
            f"👥 PEOPLE {len(state['borrowers'])} │ 🔄 OPEN {len(open_loans)} │ "
            f"⚠️ LATE {overdue_count}"
        )
    line(score, centered=True, background=BG_PANEL, foreground=FG_WHITE)
    border("╠", "═", "╣", BG_TEAL)
    line("✦  MAIN MENU  ✦", centered=True, background=BG_TEAL, foreground=FG_WHITE + BOLD)
    border("╠", "═", "╣", BG_PANEL)
    options = [
        ("[1] 💻 Register laptop", "[2] 👤 Register borrower"),
        ("[3] 🔄 Create loan", "[4] 📋 Pending / overdue loans"),
        ("[5] 📥 Record return", "[6] ✅ Available laptops"),
        ("[7] 🕘 Loan history", "[0] 💾 Save and exit"),
    ]
    if double_column:
        for left, right in options:
            line(f"{left:<34}  {right}", background=BG_PANEL, foreground=FG_WHITE)
    else:
        for left, right in options:
            line(left, background=BG_PANEL, foreground=FG_WHITE)
            line(right, background=BG_PANEL, foreground=FG_WHITE)
    border("╚", "═", "╝", BG_PANEL)
    print(f"{FG_MUTED}  Choose an option  [0–7]   •   Type 5 or 5. to record a return{RESET}")


def empty_state() -> dict:
    return {"equipment": [], "borrowers": [], "loans": [], "next_id": 1}


def load_state() -> dict:
    if not DATA_FILE.exists():
        return empty_state()
    try:
        state = json.loads(DATA_FILE.read_text(encoding="utf-8"))
        for key in ("equipment", "borrowers", "loans"):
            if not isinstance(state.get(key), list):
                raise ValueError(f"Invalid '{key}' data in {DATA_FILE.name}.")
        state["next_id"] = int(state.get("next_id", 1))
        return state
    except (OSError, json.JSONDecodeError, ValueError, TypeError) as exc:
        raise RuntimeError(f"Could not load {DATA_FILE.name}: {exc}") from exc


def save_state(state: dict) -> None:
    temporary_file = DATA_FILE.with_suffix(".json.tmp")
    temporary_file.write_text(json.dumps(state, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    temporary_file.replace(DATA_FILE)


def prompt_date(message: str, default_today: bool = False) -> date | None:
    raw = input(message).strip()
    if not raw and default_today:
        return TODAY()
    try:
        return datetime.strptime(raw, "%Y-%m-%d").date()
    except ValueError:
        print("Invalid date. Use YYYY-MM-DD, for example 2026-10-30.")
        return None


def pending_loans(state: dict) -> list[dict]:
    return [loan for loan in state["loans"] if not loan.get("return_date")]


def add_equipment(state: dict) -> None:
    code = input("Laptop asset code: ").strip().upper()
    description = input("Description (brand/model): ").strip()
    if not re.fullmatch(r"[A-Z0-9][A-Z0-9-]{1,19}", code):
        print("Invalid code. Use 2-20 letters, numbers, or hyphens.")
        return
    if not 2 <= len(description) <= 80:
        print("Description must contain 2-80 characters.")
        return
    if any(item["code"] == code for item in state["equipment"]):
        print("A laptop with that asset code is already registered.")
        return
    state["equipment"].append({"code": code, "description": description, "active": True})
    save_state(state)
    print_message("Laptop registered.", "success")


def add_borrower(state: dict) -> None:
    document = input("Borrower ID: ").strip()
    name = input("Full name: ").strip()
    contact = input("Contact (optional): ").strip()
    if not re.fullmatch(r"[\w.-]{3,25}", document, flags=re.UNICODE):
        print("Invalid ID. Use 3-25 letters, numbers, periods, or hyphens.")
        return
    if not 2 <= len(name) <= 80 or not all(ch.isalpha() or ch in " '-." for ch in name):
        print("Invalid name. Use 2-80 letters, spaces, apostrophes, periods, or hyphens.")
        return
    email_ok = re.fullmatch(r"[^\s@]+@[^\s@]+\.[^\s@]+", contact)
    phone_ok = re.fullmatch(r"\+?\d[\d ()-]{5,19}", contact)
    if contact and not (email_ok or phone_ok):
        print("Invalid contact. Enter a phone number or email address.")
        return
    if any(person["document"] == document for person in state["borrowers"]):
        print("A borrower with that ID is already registered.")
        return
    state["borrowers"].append({"document": document, "name": name, "contact": contact})
    save_state(state)
    print_message("Borrower registered.", "success")


def is_supported_image(path: Path) -> bool:
    if not path.is_file() or path.suffix.lower() not in {".jpg", ".jpeg", ".png"}:
        return False
    try:
        with path.open("rb") as image_file:
            header = image_file.read(8)
    except OSError:
        return False
    png_signature = b"\x89PNG\r\n\x1a\n"
    return header.startswith(png_signature) or header.startswith(b"\xff\xd8\xff")


def get_photo_evidence(loan_id: int) -> str | None:
    print("Take a photo of the laptop before handing it over.")
    if os.name == "nt":
        try:
            os.startfile("microsoft.windows.camera:")  # type: ignore[attr-defined]
        except OSError:
            print("Camera did not open. Take the photo with another app, then enter its file path.")
    raw_path = input("Path to the JPG/PNG photo (press Enter to cancel): ").strip().strip('"')
    if not raw_path:
        print("Loan cancelled because photo evidence is required.")
        return None
    source = Path(raw_path).expanduser()
    if not is_supported_image(source):
        print("Invalid image. Select an existing JPG or PNG image file.")
        return None
    try:
        EVIDENCE_DIR.mkdir(parents=True, exist_ok=True)
        destination = EVIDENCE_DIR / f"loan-{loan_id}{source.suffix.lower()}"
        shutil.copy2(source, destination)
    except OSError as exc:
        print(f"Could not save the photo: {exc}")
        return None
    return destination.relative_to(ROOT).as_posix()


def create_loan(state: dict) -> None:
    code = input("Laptop asset code: ").strip().upper()
    equipment = next(
        (item for item in state["equipment"] if item["code"] == code and item.get("active", True)),
        None,
    )
    if not equipment:
        print("No active laptop with that asset code was found.")
        return
    if any(loan["equipment_code"] == code for loan in pending_loans(state)):
        print("This laptop already has an open loan.")
        return

    document = input("Borrower ID: ").strip()
    borrower = next((person for person in state["borrowers"] if person["document"] == document), None)
    if not borrower:
        print("Borrower not found. Register them first (option 2).")
        return
    if any(loan["document"] == document for loan in pending_loans(state)):
        print(f"Loan blocked: {borrower['name']} must return their current laptop first.")
        return

    loan_date = prompt_date(f"Checkout date [Enter = {TODAY().isoformat()}]: ", default_today=True)
    if loan_date is None:
        return
    if loan_date > TODAY():
        print("Checkout date cannot be in the future.")
        return
    due_date = prompt_date("Due date (YYYY-MM-DD): ")
    if due_date is None:
        return
    if due_date < loan_date:
        print("Due date cannot be earlier than the checkout date.")
        return

    notes = input("Notes or included accessories (optional): ").strip()
    loan_id = state["next_id"]
    photo_path = get_photo_evidence(loan_id)
    if not photo_path:
        return
    state["loans"].append(
        {
            "id": loan_id,
            "equipment_code": code,
            "description": equipment["description"],
            "document": document,
            "borrower_name": borrower["name"],
            "loan_date": loan_date.isoformat(),
            "due_date": due_date.isoformat(),
            "return_date": None,
            "notes": notes,
            "photo_path": photo_path,
        }
    )
    state["next_id"] += 1
    save_state(state)
    print_message("Loan registered.", "success")


def show_pending(state: dict) -> None:
    loans = pending_loans(state)
    if not loans:
        print("There are no pending loans.")
        return
    today = TODAY().isoformat()
    for loan in sorted(loans, key=lambda item: (item["due_date"], item["equipment_code"])):
        status = "OVERDUE" if loan["due_date"] < today else "current"
        print(
            f"#{loan['id']} | {loan['equipment_code']} ({loan['description']}) | "
            f"{loan['borrower_name']} [{loan['document']}] | checked out {loan['loan_date']} | "
            f"due {loan['due_date']} | {status} | photo {loan.get('photo_path', '')} | {loan['notes']}"
        )


def return_equipment(state: dict) -> None:
    show_pending(state)
    raw_id = input("Loan number to return (press Enter to cancel): ").strip()
    if not raw_id:
        return
    if not raw_id.isdigit():
        print("Enter a valid loan number.")
        return
    loan = next((item for item in pending_loans(state) if item["id"] == int(raw_id)), None)
    if not loan:
        print("No open loan was found with that number.")
        return
    return_date = prompt_date(f"Return date [Enter = {TODAY().isoformat()}]: ", default_today=True)
    if return_date is None:
        return
    loan_date = date.fromisoformat(loan["loan_date"])
    if return_date < loan_date or return_date > TODAY():
        print("Return date must be between the checkout date and today.")
        return
    loan["return_date"] = return_date.isoformat()
    save_state(state)
    print_message("Return recorded; the laptop is available again.", "success")


def show_available(state: dict) -> None:
    open_codes = {loan["equipment_code"] for loan in pending_loans(state)}
    available = [
        item for item in state["equipment"] if item.get("active", True) and item["code"] not in open_codes
    ]
    if not available:
        print("There are no available laptops.")
        return
    for item in sorted(available, key=lambda laptop: laptop["code"]):
        print(f"{item['code']} - {item['description']}")


def show_history(state: dict) -> None:
    loans = sorted(state["loans"], key=lambda item: item["id"], reverse=True)[:30]
    if not loans:
        print("No loans have been recorded yet.")
        return
    for loan in loans:
        returned = loan.get("return_date") or "pending"
        print(
            f"{loan['equipment_code']} | {loan['borrower_name']} | "
            f"{loan['loan_date']} -> {loan['due_date']} | returned: {returned} | "
            f"photo: {loan.get('photo_path', '')} | {loan['notes']}"
        )


def main() -> None:
    try:
        state = load_state()
    except RuntimeError as exc:
        print(exc)
        return

    actions = {
        "1": add_equipment,
        "2": add_borrower,
        "3": create_loan,
        "4": show_pending,
        "5": return_equipment,
        "6": show_available,
        "7": show_history,
    }
    while True:
        draw_menu(state)
        try:
            choice = input(f"{BOLD}{CYAN}Choose an option [0-7]: {RESET}").strip().rstrip(".").strip()
            if choice == "0":
                print_message("Changes are saved. Goodbye!", "success")
                break
            action = actions.get(choice)
            if action:
                action(state)
            else:
                print_message("Invalid option. Enter a number from 0 to 7.", "error")
        except (KeyboardInterrupt, EOFError):
            print_message("\nExiting. Previously saved records are preserved.", "warning")
            break
        except OSError as exc:
            print_message(f"Could not save data: {exc}", "error")


if __name__ == "__main__":
    main()
