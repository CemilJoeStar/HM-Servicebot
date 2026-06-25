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


if __name__ == "__main__":
    unittest.main()
