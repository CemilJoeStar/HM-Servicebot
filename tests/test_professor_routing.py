import unittest
from unittest.mock import patch

import rag_prototype


PROFESSORS = [
    {
        "display_name": "Prof. Dr. Markus Brandt",
        "focus_topics": ["Software Engineering", "Cloud-Anwendungen", "IT-Sicherheit"],
        "capacity_status": "limited",
        "available_slots": 1,
    },
    {
        "display_name": "Prof. Dr. Selin Aydin",
        "focus_topics": [
            "Digitale Prozesse",
            "Geschäftsprozessmanagement",
            "Projektseminar",
        ],
        "capacity_status": "available",
        "available_slots": 2,
    },
    {
        "display_name": "Prof. Dr. Anna Keller",
        "focus_topics": ["Data Analytics", "Business Intelligence", "Process Mining"],
        "capacity_status": "available",
        "available_slots": 3,
    },
    {
        "display_name": "Prof. Dr. David Nguyen",
        "focus_topics": ["Cybersecurity", "Datenschutz", "Cloud Security"],
        "capacity_status": "limited",
        "available_slots": 1,
        "email": "david.nguyen@hm.example",
    },
]

PROFILE = {
    "notes": {
        "interests": ["Digitale Prozesse", "Data Analytics"],
        "completed_modules": [
            {"name": "Geschäftsprozessmanagement"},
            {"name": "Business Intelligence"},
        ],
        "open_modules": [{"name": "Projektseminar"}],
    }
}


class ProfessorRoutingTests(unittest.TestCase):
    def test_explicit_cloud_request_uses_professor_matching(self):
        route = rag_prototype.route_intent(
            "Ich möchte meine Bachelorarbeit im Bereich Cloud schreiben. "
            "Wen kannst du mir empfehlen?"
        )

        self.assertEqual(route.intent, "professor_matching")

    @patch("rag_prototype.get_professors", return_value=PROFESSORS)
    def test_explicit_topic_overrides_profile_similarity(self, _get_professors):
        recommendations = rag_prototype.recommend_professors(
            PROFILE,
            query="Bachelorarbeit im Bereich Cloud, wen kannst du empfehlen?",
        )

        self.assertEqual(
            [item.display_name for item in recommendations],
            ["Prof. Dr. Markus Brandt"],
        )

    @patch("rag_prototype.get_professors", return_value=PROFESSORS)
    def test_generic_request_still_uses_profile(self, _get_professors):
        recommendations = rag_prototype.recommend_professors(
            PROFILE,
            query="Wen würdest du mir für meine Bachelorarbeit empfehlen?",
        )

        self.assertEqual(recommendations[0].display_name, "Prof. Dr. Selin Aydin")

    def test_topic_correction_keeps_professor_context(self):
        messages = [
            {
                "role": "assistant",
                "text": "Für dein Profil passen diese Betreuungspersonen.",
                "routeLabel": "Professorenmatching",
            }
        ]

        route = rag_prototype.route_intent_with_context(
            "Aber ich meinte doch Cloud.",
            messages,
        )

        self.assertEqual(route.intent, "professor_matching")

    @patch("rag_prototype.get_professors", return_value=PROFESSORS)
    def test_software_development_synonym_matches_software_engineering(
        self,
        _get_professors,
    ):
        recommendations = rag_prototype.recommend_professors(
            PROFILE,
            query="Ich möchte über Softwareentwicklung schreiben.",
        )

        self.assertEqual(
            [item.display_name for item in recommendations],
            ["Prof. Dr. Markus Brandt"],
        )

    @patch("rag_prototype.get_professors", return_value=PROFESSORS)
    def test_named_professor_returns_details_instead_of_generic_ranking(
        self,
        _get_professors,
    ):
        answer = rag_prototype.answer_professor_question(
            "Was ist mit Prof. Nguyen?",
            PROFILE,
        )

        self.assertIn("Prof. Dr. David Nguyen", answer["answer"])
        self.assertIn("Cybersecurity", answer["answer"])
        self.assertIn("begrenzt verfügbar", answer["answer"])
        self.assertNotIn("Prof. Dr. Selin Aydin", answer["answer"])


class TypoToleranceTests(unittest.TestCase):
    def test_bachelorarbeit_typo_is_normalized(self):
        normalized = rag_prototype.normalize_question(
            "Wann kann ich meine bachelorarebit schreiben?"
        )

        self.assertIn("bachelorarbeit", normalized)

    def test_combined_ects_and_thesis_question_routes_to_advising(self):
        route = rag_prototype.route_intent(
            "Wie viele ECTS habe ich aktuell und wann kann ich "
            "meine bachelorarebit schreiben?"
        )

        self.assertEqual(route.intent, "advising")

    def test_combined_question_answers_current_and_missing_ects(self):
        profile = {
            "ects_earned": 118,
            "notes": {
                "open_modules": [
                    {"name": "IT-Sicherheit"},
                    {"name": "Projektseminar"},
                ]
            },
        }

        answer = rag_prototype.answer_profile_question(
            "Wie viele ECTS habe ich aktuell und wann kann ich "
            "meine bachelorarebit schreiben?",
            profile,
        )

        self.assertIn("118 ECTS", answer["answer"])
        self.assertIn("mindestens 120 ECTS", answer["answer"])
        self.assertIn("noch 2 ECTS", answer["answer"])


if __name__ == "__main__":
    unittest.main()
