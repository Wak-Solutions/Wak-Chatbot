"""
test_intent.py — Unit tests for intent.py.

intent.py is pure (no I/O, no DB, no network), so these tests need no mocks
and run synchronously. They cover every keyword set and edge case.
"""

import pytest

from intent import (
    ai_scheduling_manually,
    is_resolved,
    wants_escalation,
    wants_meeting,
)


# ── is_resolved ───────────────────────────────────────────────────────────────


class TestIsResolved:
    def test_specialist_will_be_in_touch(self):
        assert is_resolved("a specialist will be in touch shortly")

    def test_member_of_team(self):
        assert is_resolved("A member of our team will follow up with you soon")

    def test_team_will_follow_up(self):
        assert is_resolved("the team will follow up as soon as possible")

    def test_will_be_in_touch_shortly(self):
        assert is_resolved("Thanks! We will be in touch shortly.")

    def test_generic_message_not_resolved(self):
        assert not is_resolved("How can I help you today?")

    def test_empty_string(self):
        assert not is_resolved("")


# ── wants_meeting ─────────────────────────────────────────────────────────────


class TestWantsMeeting:
    def test_book_keyword(self):
        assert wants_meeting("I want to book a demo")

    def test_meeting_keyword(self):
        assert wants_meeting("Can we arrange a meeting?")

    def test_schedule_keyword(self):
        assert wants_meeting("I'd like to schedule a call")

    def test_appointment_keyword(self):
        assert wants_meeting("I need an appointment")

    def test_slot_keyword(self):
        assert wants_meeting("Do you have a free slot?")

    def test_arabic_meeting(self):
        assert wants_meeting("اريد حجز موعد")

    def test_arabic_appointment(self):
        assert wants_meeting("هل يمكن ترتيب اجتماع")

    def test_ambiguous_yes_without_context(self):
        # "yes" alone, no prior bot context → should NOT trigger meeting intent
        assert not wants_meeting("yes")

    def test_ambiguous_yes_with_meeting_context(self):
        history = [{"role": "assistant", "content": "Would you like to schedule a meeting with our team?"}]
        assert wants_meeting("yes", history)

    def test_ambiguous_ok_without_context(self):
        assert not wants_meeting("ok")

    def test_generic_question_no_meeting(self):
        assert not wants_meeting("What products do you offer?")

    def test_no_false_positive_complaint(self):
        assert not wants_meeting("I have a complaint about my order")


# ── wants_escalation ──────────────────────────────────────────────────────────


class TestWantsEscalation:
    def test_agent_keyword(self):
        assert wants_escalation("I want to speak to an agent")

    def test_human_keyword(self):
        assert wants_escalation("Can I talk to a human?")

    def test_speak_to_someone(self):
        assert wants_escalation("I'd like to speak to someone")

    def test_real_person(self):
        assert wants_escalation("I want a real person")

    def test_customer_service(self):
        assert wants_escalation("connect me to customer service")

    def test_arabic_agent(self):
        assert wants_escalation("اريد التحدث مع وكيل")

    def test_arabic_human(self):
        assert wants_escalation("اريد انسان")

    def test_ambiguous_yes_without_agent_offer(self):
        # "yes" without prior agent offer → should NOT escalate
        assert not wants_escalation("yes")

    def test_ambiguous_yes_with_agent_offer(self):
        history = [
            {"role": "assistant", "content": "Would you like to speak with a customer service agent on WhatsApp?"}
        ]
        assert wants_escalation("yes", history)

    def test_generic_message_no_escalation(self):
        assert not wants_escalation("Tell me about your products")


# ── ai_scheduling_manually ────────────────────────────────────────────────────


class TestAiSchedulingManually:
    def test_what_date(self):
        assert ai_scheduling_manually("What date would you prefer?")

    def test_what_time(self):
        assert ai_scheduling_manually("What time works for you?")

    def test_when_would_you_like(self):
        assert ai_scheduling_manually("When would you like to meet?")

    def test_preferred_time(self):
        assert ai_scheduling_manually("Please let me know your preferred time.")

    def test_arabic_scheduling(self):
        assert ai_scheduling_manually("أي يوم تفضل للاجتماع؟")

    def test_normal_reply_not_scheduling(self):
        assert not ai_scheduling_manually("Here is your order status: shipped.")

    def test_booking_link_reply_not_scheduling(self):
        assert not ai_scheduling_manually("Here's your booking link: http://example.com/book/abc")
