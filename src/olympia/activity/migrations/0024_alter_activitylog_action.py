# Generated by Django 4.2.1 on 2023-05-24 08:34

from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ('activity', '0023_remove_draftcomment_canned_response'),
    ]

    operations = [
        migrations.AlterField(
            model_name='activitylog',
            name='action',
            field=models.SmallIntegerField(
                choices=[
                    (1, 1),
                    (2, 2),
                    (3, 3),
                    (4, 4),
                    (5, 5),
                    (6, 6),
                    (7, 7),
                    (8, 8),
                    (9, 9),
                    (12, 12),
                    (16, 16),
                    (17, 17),
                    (18, 18),
                    (19, 19),
                    (20, 20),
                    (21, 21),
                    (22, 22),
                    (23, 23),
                    (24, 24),
                    (25, 25),
                    (26, 26),
                    (27, 27),
                    (28, 28),
                    (29, 29),
                    (31, 31),
                    (32, 32),
                    (33, 33),
                    (34, 34),
                    (35, 35),
                    (36, 36),
                    (37, 37),
                    (38, 38),
                    (39, 39),
                    (40, 40),
                    (41, 41),
                    (42, 42),
                    (43, 43),
                    (44, 44),
                    (45, 45),
                    (46, 46),
                    (47, 47),
                    (48, 48),
                    (49, 49),
                    (53, 53),
                    (60, 60),
                    (61, 61),
                    (62, 62),
                    (98, 98),
                    (99, 99),
                    (100, 100),
                    (101, 101),
                    (102, 102),
                    (103, 103),
                    (104, 104),
                    (105, 105),
                    (106, 106),
                    (107, 107),
                    (108, 108),
                    (109, 109),
                    (110, 110),
                    (120, 120),
                    (121, 121),
                    (128, 128),
                    (130, 130),
                    (131, 131),
                    (132, 132),
                    (133, 133),
                    (134, 134),
                    (135, 135),
                    (136, 136),
                    (137, 137),
                    (138, 138),
                    (139, 139),
                    (140, 140),
                    (141, 141),
                    (142, 142),
                    (143, 143),
                    (144, 144),
                    (145, 145),
                    (146, 146),
                    (147, 147),
                    (148, 148),
                    (149, 149),
                    (150, 150),
                    (151, 151),
                    (152, 152),
                    (153, 153),
                    (154, 154),
                    (155, 155),
                    (156, 156),
                    (157, 157),
                    (158, 158),
                    (159, 159),
                    (160, 160),
                    (161, 161),
                    (162, 162),
                    (163, 163),
                    (164, 164),
                    (165, 165),
                    (166, 166),
                    (167, 167),
                    (168, 168),
                    (169, 169),
                    (170, 170),
                    (171, 171),
                    (172, 172),
                    (173, 173),
                    (174, 174),
                    (175, 175),
                ]
            ),
        ),
    ]
