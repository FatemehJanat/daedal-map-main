"""
Generate reference.json files for each SDG goal.

These provide conceptual context for the LLM to answer questions
like "tell me about SDG 1" or "what are the poverty targets?".

Source: UN SDG Knowledge Portal - https://sdgs.un.org/goals
"""

import json
from pathlib import Path

OUTPUT_DIR = Path("C:/Users/Bryan/Desktop/county-map-data/data")

# SDG Reference Data
# Source: https://sdgs.un.org/goals
SDG_REFERENCES = {
    1: {
        "source_context": "United Nations Sustainable Development Goals Framework",
        "goal": {
            "number": 1,
            "name": "No Poverty",
            "full_title": "End poverty in all its forms everywhere",
            "description": "Goal 1 calls for an end to poverty in all its manifestations by 2030. It also aims to ensure social protection for the poor and vulnerable, increase access to basic services and support people harmed by climate-related extreme events and other economic, social and environmental shocks and disasters.",
            "targets": [
                {"id": "1.1", "text": "By 2030, eradicate extreme poverty for all people everywhere, currently measured as people living on less than $2.15 a day"},
                {"id": "1.2", "text": "By 2030, reduce at least by half the proportion of men, women and children of all ages living in poverty in all its dimensions according to national definitions"},
                {"id": "1.3", "text": "Implement nationally appropriate social protection systems and measures for all"},
                {"id": "1.4", "text": "Ensure all men and women, particularly the poor and vulnerable, have equal rights to economic resources, basic services, ownership and control over land and other forms of property"},
                {"id": "1.5", "text": "Build the resilience of the poor and those in vulnerable situations and reduce their exposure to climate-related extreme events"},
            ],
            "key_indicators": ["SI_POV_DAY1 - Population below $2.15/day", "SI_POV_EMP1 - Employed population below poverty line"]
        },
        "shared_with": ["un_sdg_08", "un_sdg_10"]
    },
    2: {
        "source_context": "United Nations Sustainable Development Goals Framework",
        "goal": {
            "number": 2,
            "name": "Zero Hunger",
            "full_title": "End hunger, achieve food security and improved nutrition and promote sustainable agriculture",
            "description": "Goal 2 seeks to end hunger and all forms of malnutrition by 2030. It commits to universal access to safe, nutritious and sufficient food, and to double agricultural productivity and incomes of small-scale food producers.",
            "targets": [
                {"id": "2.1", "text": "By 2030, end hunger and ensure access by all people to safe, nutritious and sufficient food all year round"},
                {"id": "2.2", "text": "By 2030, end all forms of malnutrition, including achieving targets on stunting and wasting in children under 5 years of age"},
                {"id": "2.3", "text": "By 2030, double the agricultural productivity and incomes of small-scale food producers"},
                {"id": "2.4", "text": "By 2030, ensure sustainable food production systems and implement resilient agricultural practices"},
                {"id": "2.5", "text": "Maintain genetic diversity of seeds, cultivated plants, farmed and domesticated animals and their related wild species"},
            ],
            "key_indicators": ["SN_ITK_DEFC - Prevalence of undernourishment", "SN_STA_OVWGT - Prevalence of overweight"]
        }
    },
    3: {
        "source_context": "United Nations Sustainable Development Goals Framework",
        "goal": {
            "number": 3,
            "name": "Good Health and Well-being",
            "full_title": "Ensure healthy lives and promote well-being for all at all ages",
            "description": "Goal 3 aims to ensure healthy lives and promote well-being for all at all ages. It addresses all major health priorities, including reproductive, maternal and child health; communicable, non-communicable and environmental diseases; universal health coverage; and access to medicines and vaccines.",
            "targets": [
                {"id": "3.1", "text": "By 2030, reduce the global maternal mortality ratio to less than 70 per 100,000 live births"},
                {"id": "3.2", "text": "By 2030, end preventable deaths of newborns and children under 5 years of age"},
                {"id": "3.3", "text": "By 2030, end the epidemics of AIDS, tuberculosis, malaria and neglected tropical diseases"},
                {"id": "3.4", "text": "By 2030, reduce by one third premature mortality from non-communicable diseases"},
                {"id": "3.5", "text": "Strengthen the prevention and treatment of substance abuse"},
                {"id": "3.6", "text": "By 2020, halve the number of global deaths and injuries from road traffic accidents"},
                {"id": "3.7", "text": "By 2030, ensure universal access to sexual and reproductive health-care services"},
                {"id": "3.8", "text": "Achieve universal health coverage, including financial risk protection and access to quality essential health-care services"},
            ],
            "key_indicators": ["SH_STA_MORT - Maternal mortality ratio", "SH_DYN_MORT - Under-5 mortality rate"]
        }
    },
    4: {
        "source_context": "United Nations Sustainable Development Goals Framework",
        "goal": {
            "number": 4,
            "name": "Quality Education",
            "full_title": "Ensure inclusive and equitable quality education and promote lifelong learning opportunities for all",
            "description": "Goal 4 aims to ensure inclusive and equitable quality education at all levels. It focuses on access to early childhood development, free primary and secondary education, affordable vocational training, and eliminating gender and wealth disparities.",
            "targets": [
                {"id": "4.1", "text": "By 2030, ensure all girls and boys complete free, equitable and quality primary and secondary education"},
                {"id": "4.2", "text": "By 2030, ensure all girls and boys have access to quality early childhood development"},
                {"id": "4.3", "text": "By 2030, ensure equal access for all women and men to affordable and quality technical, vocational and tertiary education"},
                {"id": "4.4", "text": "By 2030, substantially increase the number of youth and adults who have relevant skills for employment"},
                {"id": "4.5", "text": "By 2030, eliminate gender disparities in education and ensure equal access for the vulnerable"},
                {"id": "4.6", "text": "By 2030, ensure all youth and a substantial proportion of adults achieve literacy and numeracy"},
            ],
            "key_indicators": ["SE_PRE_PARTN - Participation rate in pre-primary education", "SE_TOT_CPLR - Completion rate"]
        }
    },
    5: {
        "source_context": "United Nations Sustainable Development Goals Framework",
        "goal": {
            "number": 5,
            "name": "Gender Equality",
            "full_title": "Achieve gender equality and empower all women and girls",
            "description": "Goal 5 aims to achieve gender equality and empower all women and girls. It targets ending all forms of discrimination and violence against women, eliminating harmful practices, ensuring equal participation in leadership, and providing universal access to reproductive rights.",
            "targets": [
                {"id": "5.1", "text": "End all forms of discrimination against all women and girls everywhere"},
                {"id": "5.2", "text": "Eliminate all forms of violence against all women and girls in the public and private spheres"},
                {"id": "5.3", "text": "Eliminate all harmful practices, such as child, early and forced marriage and female genital mutilation"},
                {"id": "5.4", "text": "Recognize and value unpaid care and domestic work through public services and social protection policies"},
                {"id": "5.5", "text": "Ensure women's full and effective participation and equal opportunities for leadership at all levels"},
                {"id": "5.6", "text": "Ensure universal access to sexual and reproductive health and reproductive rights"},
            ],
            "key_indicators": ["SG_GEN_PARL - Proportion of seats held by women in national parliaments"]
        }
    },
    6: {
        "source_context": "United Nations Sustainable Development Goals Framework",
        "goal": {
            "number": 6,
            "name": "Clean Water and Sanitation",
            "full_title": "Ensure availability and sustainable management of water and sanitation for all",
            "description": "Goal 6 focuses on ensuring availability and sustainable management of water and sanitation for all. It addresses safe drinking water, sanitation, hygiene, water quality, water-use efficiency, integrated water resources management, and protecting water-related ecosystems.",
            "targets": [
                {"id": "6.1", "text": "By 2030, achieve universal and equitable access to safe and affordable drinking water for all"},
                {"id": "6.2", "text": "By 2030, achieve access to adequate and equitable sanitation and hygiene for all"},
                {"id": "6.3", "text": "By 2030, improve water quality by reducing pollution and minimizing release of hazardous chemicals"},
                {"id": "6.4", "text": "By 2030, substantially increase water-use efficiency across all sectors"},
                {"id": "6.5", "text": "By 2030, implement integrated water resources management at all levels"},
                {"id": "6.6", "text": "By 2020, protect and restore water-related ecosystems"},
            ],
            "key_indicators": ["SH_H2O_SAFE - Population using safely managed drinking water services", "SH_SAN_SAFE - Population using safely managed sanitation services"]
        }
    },
    7: {
        "source_context": "United Nations Sustainable Development Goals Framework",
        "goal": {
            "number": 7,
            "name": "Affordable and Clean Energy",
            "full_title": "Ensure access to affordable, reliable, sustainable and modern energy for all",
            "description": "Goal 7 aims to ensure access to affordable, reliable, sustainable and modern energy for all. It focuses on universal access to electricity and clean cooking fuels, increasing the share of renewable energy, improving energy efficiency, and enhancing international cooperation on clean energy research.",
            "targets": [
                {"id": "7.1", "text": "By 2030, ensure universal access to affordable, reliable and modern energy services"},
                {"id": "7.2", "text": "By 2030, increase substantially the share of renewable energy in the global energy mix"},
                {"id": "7.3", "text": "By 2030, double the global rate of improvement in energy efficiency"},
            ],
            "key_indicators": ["EG_ELC_ACCS - Population with access to electricity", "EG_FEC_RNEW - Renewable energy share"]
        }
    },
    8: {
        "source_context": "United Nations Sustainable Development Goals Framework",
        "goal": {
            "number": 8,
            "name": "Decent Work and Economic Growth",
            "full_title": "Promote sustained, inclusive and sustainable economic growth, full and productive employment and decent work for all",
            "description": "Goal 8 promotes sustained, inclusive economic growth, full and productive employment and decent work for all. It addresses GDP growth, economic productivity, job creation, entrepreneurship, labor rights, safe working environments, and sustainable tourism.",
            "targets": [
                {"id": "8.1", "text": "Sustain per capita economic growth in accordance with national circumstances"},
                {"id": "8.2", "text": "Achieve higher levels of economic productivity through diversification, technological upgrading and innovation"},
                {"id": "8.3", "text": "Promote development-oriented policies that support productive activities and decent job creation"},
                {"id": "8.4", "text": "Improve progressively global resource efficiency in consumption and production"},
                {"id": "8.5", "text": "By 2030, achieve full and productive employment and decent work for all"},
                {"id": "8.6", "text": "By 2020, substantially reduce the proportion of youth not in employment, education or training"},
                {"id": "8.7", "text": "Take immediate and effective measures to eradicate forced labour and end child labour"},
                {"id": "8.8", "text": "Protect labour rights and promote safe and secure working environments"},
            ],
            "key_indicators": ["SL_EMP_PCAP - GDP per employed person", "SL_TLF_UEM - Unemployment rate"]
        },
        "shared_with": ["un_sdg_01", "un_sdg_10"]
    },
    9: {
        "source_context": "United Nations Sustainable Development Goals Framework",
        "goal": {
            "number": 9,
            "name": "Industry, Innovation and Infrastructure",
            "full_title": "Build resilient infrastructure, promote inclusive and sustainable industrialization and foster innovation",
            "description": "Goal 9 focuses on building resilient infrastructure, promoting inclusive and sustainable industrialization and fostering innovation. It addresses quality infrastructure, sustainable industrialization, access to financial services for small enterprises, technological capabilities, and research and development.",
            "targets": [
                {"id": "9.1", "text": "Develop quality, reliable, sustainable and resilient infrastructure to support economic development"},
                {"id": "9.2", "text": "Promote inclusive and sustainable industrialization and raise industry's share of employment and GDP"},
                {"id": "9.3", "text": "Increase the access of small-scale industrial and other enterprises to financial services"},
                {"id": "9.4", "text": "Upgrade infrastructure and retrofit industries to make them sustainable with increased resource-use efficiency"},
                {"id": "9.5", "text": "Enhance scientific research, upgrade technological capabilities of industrial sectors"},
            ],
            "key_indicators": ["NV_IND_MANFP - Manufacturing value added as proportion of GDP", "GB_XPD_RSDV - Research and development expenditure"]
        }
    },
    10: {
        "source_context": "United Nations Sustainable Development Goals Framework",
        "goal": {
            "number": 10,
            "name": "Reduced Inequalities",
            "full_title": "Reduce inequality within and among countries",
            "description": "Goal 10 addresses reducing inequality within and among countries. It focuses on income growth for the bottom 40%, social, economic and political inclusion, equal opportunity, reduced inequalities of outcome, safe migration, and improved representation for developing countries in global institutions.",
            "targets": [
                {"id": "10.1", "text": "By 2030, achieve and sustain income growth of the bottom 40 per cent of the population at a rate higher than the national average"},
                {"id": "10.2", "text": "By 2030, empower and promote the social, economic and political inclusion of all"},
                {"id": "10.3", "text": "Ensure equal opportunity and reduce inequalities of outcome"},
                {"id": "10.4", "text": "Adopt policies, especially fiscal, wage and social protection policies, and progressively achieve greater equality"},
                {"id": "10.5", "text": "Improve the regulation and monitoring of global financial markets and institutions"},
                {"id": "10.6", "text": "Ensure enhanced representation and voice for developing countries in decision-making in global institutions"},
                {"id": "10.7", "text": "Facilitate orderly, safe, regular and responsible migration"},
            ],
            "key_indicators": ["SI_POV_GINI - Gini index", "SI_POV_50MI - Proportion living below 50% of median income"]
        },
        "shared_with": ["un_sdg_01", "un_sdg_08"]
    },
    11: {
        "source_context": "United Nations Sustainable Development Goals Framework",
        "goal": {
            "number": 11,
            "name": "Sustainable Cities and Communities",
            "full_title": "Make cities and human settlements inclusive, safe, resilient and sustainable",
            "description": "Goal 11 aims to make cities and human settlements inclusive, safe, resilient and sustainable. It addresses housing, transport systems, urbanization planning, cultural and natural heritage, disaster impacts, environmental impacts of cities, and access to green and public spaces.",
            "targets": [
                {"id": "11.1", "text": "By 2030, ensure access for all to adequate, safe and affordable housing and basic services"},
                {"id": "11.2", "text": "By 2030, provide access to safe, affordable, accessible and sustainable transport systems for all"},
                {"id": "11.3", "text": "By 2030, enhance inclusive and sustainable urbanization and capacity for participatory planning"},
                {"id": "11.4", "text": "Strengthen efforts to protect and safeguard the world's cultural and natural heritage"},
                {"id": "11.5", "text": "By 2030, significantly reduce the number of deaths and people affected by disasters"},
                {"id": "11.6", "text": "By 2030, reduce the adverse per capita environmental impact of cities"},
                {"id": "11.7", "text": "By 2030, provide universal access to safe, inclusive and accessible, green and public spaces"},
            ],
            "key_indicators": ["EN_LND_SLUM - Proportion of urban population living in slums", "EN_ATM_PM25 - Mean urban air pollution"]
        }
    },
    12: {
        "source_context": "United Nations Sustainable Development Goals Framework",
        "goal": {
            "number": 12,
            "name": "Responsible Consumption and Production",
            "full_title": "Ensure sustainable consumption and production patterns",
            "description": "Goal 12 focuses on ensuring sustainable consumption and production patterns. It addresses sustainable management of natural resources, food waste reduction, chemicals and waste management, sustainable practices by companies, sustainable public procurement, and sustainable lifestyles.",
            "targets": [
                {"id": "12.1", "text": "Implement the 10-Year Framework of Programmes on Sustainable Consumption and Production Patterns"},
                {"id": "12.2", "text": "By 2030, achieve the sustainable management and efficient use of natural resources"},
                {"id": "12.3", "text": "By 2030, halve per capita global food waste at the retail and consumer levels"},
                {"id": "12.4", "text": "By 2020, achieve environmentally sound management of chemicals and all wastes throughout their life cycle"},
                {"id": "12.5", "text": "By 2030, substantially reduce waste generation through prevention, reduction, recycling and reuse"},
                {"id": "12.6", "text": "Encourage companies to adopt sustainable practices and integrate sustainability information into their reporting cycle"},
                {"id": "12.7", "text": "Promote public procurement practices that are sustainable"},
                {"id": "12.8", "text": "By 2030, ensure that people everywhere have the relevant information and awareness for sustainable development"},
            ],
            "key_indicators": ["EN_MAT_DOMCMPC - Domestic material consumption per capita", "EN_MAT_FTPRPC - Material footprint per capita"]
        }
    },
    13: {
        "source_context": "United Nations Sustainable Development Goals Framework",
        "goal": {
            "number": 13,
            "name": "Climate Action",
            "full_title": "Take urgent action to combat climate change and its impacts",
            "description": "Goal 13 calls for urgent action to combat climate change and its impacts. It focuses on strengthening resilience and adaptive capacity to climate-related hazards, integrating climate change measures into national policies, improving education and awareness on climate change mitigation and adaptation.",
            "targets": [
                {"id": "13.1", "text": "Strengthen resilience and adaptive capacity to climate-related hazards and natural disasters in all countries"},
                {"id": "13.2", "text": "Integrate climate change measures into national policies, strategies and planning"},
                {"id": "13.3", "text": "Improve education, awareness-raising and human and institutional capacity on climate change mitigation, adaptation, impact reduction and early warning"},
            ],
            "key_indicators": ["SG_DSR_LGRGSR - National disaster risk reduction strategies", "VC_DSR_GDPLS - Direct economic loss due to disasters"]
        }
    },
    14: {
        "source_context": "United Nations Sustainable Development Goals Framework",
        "goal": {
            "number": 14,
            "name": "Life Below Water",
            "full_title": "Conserve and sustainably use the oceans, seas and marine resources for sustainable development",
            "description": "Goal 14 focuses on conserving and sustainably using the oceans, seas and marine resources. It addresses marine pollution, ocean acidification, overfishing, marine protected areas, and the sustainable use of marine resources by small island developing states and least developed countries.",
            "targets": [
                {"id": "14.1", "text": "By 2025, prevent and significantly reduce marine pollution of all kinds"},
                {"id": "14.2", "text": "By 2020, sustainably manage and protect marine and coastal ecosystems"},
                {"id": "14.3", "text": "Minimize and address the impacts of ocean acidification"},
                {"id": "14.4", "text": "By 2020, effectively regulate harvesting and end overfishing, illegal fishing and destructive fishing practices"},
                {"id": "14.5", "text": "By 2020, conserve at least 10 per cent of coastal and marine areas"},
                {"id": "14.6", "text": "By 2020, prohibit certain forms of fisheries subsidies which contribute to overcapacity and overfishing"},
                {"id": "14.7", "text": "By 2030, increase the economic benefits to small island developing States and least developed countries from the sustainable use of marine resources"},
            ],
            "key_indicators": ["ER_MRN_MPA - Protected marine areas", "ER_REG_UNFCIM - Implementation of instruments to combat illegal fishing"]
        }
    },
    15: {
        "source_context": "United Nations Sustainable Development Goals Framework",
        "goal": {
            "number": 15,
            "name": "Life on Land",
            "full_title": "Protect, restore and promote sustainable use of terrestrial ecosystems, sustainably manage forests, combat desertification, and halt and reverse land degradation and halt biodiversity loss",
            "description": "Goal 15 focuses on protecting, restoring and promoting sustainable use of terrestrial ecosystems, managing forests sustainably, combating desertification, halting and reversing land degradation, and halting biodiversity loss.",
            "targets": [
                {"id": "15.1", "text": "By 2020, ensure the conservation, restoration and sustainable use of terrestrial and inland freshwater ecosystems"},
                {"id": "15.2", "text": "By 2020, promote the implementation of sustainable management of all types of forests"},
                {"id": "15.3", "text": "By 2030, combat desertification, restore degraded land and soil"},
                {"id": "15.4", "text": "By 2030, ensure the conservation of mountain ecosystems"},
                {"id": "15.5", "text": "Take urgent and significant action to reduce the degradation of natural habitats, halt the loss of biodiversity"},
                {"id": "15.6", "text": "Promote fair and equitable sharing of the benefits arising from the utilization of genetic resources"},
                {"id": "15.7", "text": "Take urgent action to end poaching and trafficking of protected species of flora and fauna"},
                {"id": "15.8", "text": "By 2020, introduce measures to prevent the introduction and significantly reduce the impact of invasive alien species"},
                {"id": "15.9", "text": "By 2020, integrate ecosystem and biodiversity values into national and local planning"},
            ],
            "key_indicators": ["ER_PTD_TERRS - Protected terrestrial areas", "AG_LND_FRST - Forest area as proportion of total land area"]
        }
    },
    16: {
        "source_context": "United Nations Sustainable Development Goals Framework",
        "goal": {
            "number": 16,
            "name": "Peace, Justice and Strong Institutions",
            "full_title": "Promote peaceful and inclusive societies for sustainable development, provide access to justice for all and build effective, accountable and inclusive institutions at all levels",
            "description": "Goal 16 promotes peaceful and inclusive societies, provides access to justice for all and builds effective, accountable and inclusive institutions. It addresses violence, abuse, trafficking, rule of law, illicit financial flows, corruption, transparent institutions, and inclusive decision-making.",
            "targets": [
                {"id": "16.1", "text": "Significantly reduce all forms of violence and related death rates everywhere"},
                {"id": "16.2", "text": "End abuse, exploitation, trafficking and all forms of violence against and torture of children"},
                {"id": "16.3", "text": "Promote the rule of law at the national and international levels and ensure equal access to justice for all"},
                {"id": "16.4", "text": "By 2030, significantly reduce illicit financial and arms flows, strengthen the recovery and return of stolen assets"},
                {"id": "16.5", "text": "Substantially reduce corruption and bribery in all their forms"},
                {"id": "16.6", "text": "Develop effective, accountable and transparent institutions at all levels"},
                {"id": "16.7", "text": "Ensure responsive, inclusive, participatory and representative decision-making at all levels"},
                {"id": "16.9", "text": "By 2030, provide legal identity for all, including birth registration"},
                {"id": "16.10", "text": "Ensure public access to information and protect fundamental freedoms"},
            ],
            "key_indicators": ["VC_VOV_GDSD - Intentional homicide rate", "SG_REG_BRTH - Birth registration"]
        }
    },
    17: {
        "source_context": "United Nations Sustainable Development Goals Framework",
        "goal": {
            "number": 17,
            "name": "Partnerships for the Goals",
            "full_title": "Strengthen the means of implementation and revitalize the Global Partnership for Sustainable Development",
            "description": "Goal 17 focuses on strengthening the means of implementation and revitalizing the Global Partnership for Sustainable Development. It addresses finance, technology, capacity-building, trade, policy coherence, partnerships, and data monitoring and accountability.",
            "targets": [
                {"id": "17.1", "text": "Strengthen domestic resource mobilization, including through international support to developing countries"},
                {"id": "17.2", "text": "Developed countries to implement fully their official development assistance commitments"},
                {"id": "17.3", "text": "Mobilize additional financial resources for developing countries from multiple sources"},
                {"id": "17.4", "text": "Assist developing countries in attaining long-term debt sustainability"},
                {"id": "17.6", "text": "Enhance North-South, South-South and triangular regional and international cooperation on and access to science, technology and innovation"},
                {"id": "17.8", "text": "Fully operationalize the technology bank and science, technology and innovation capacity-building mechanism for least developed countries"},
                {"id": "17.9", "text": "Enhance international support for implementing effective and targeted capacity-building in developing countries"},
                {"id": "17.10", "text": "Promote a universal, rules-based, open, non-discriminatory and equitable multilateral trading system under the WTO"},
                {"id": "17.11", "text": "Significantly increase the exports of developing countries"},
                {"id": "17.18", "text": "Enhance capacity-building support to developing countries to increase significantly the availability of high-quality, timely and reliable data"},
                {"id": "17.19", "text": "By 2030, build on existing initiatives to develop measurements of progress on sustainable development"},
            ],
            "key_indicators": ["DC_ODA_TOTL - Net ODA as proportion of GNI", "IT_NET_USER - Internet users"]
        }
    }
}


def main():
    """Generate reference.json files for all SDG goals."""
    print("Generating SDG reference files...")

    for goal_num, reference in SDG_REFERENCES.items():
        source_id = f"un_sdg_{goal_num:02d}"
        output_dir = OUTPUT_DIR / source_id
        output_path = output_dir / "reference.json"

        if output_dir.exists():
            with open(output_path, 'w', encoding='utf-8') as f:
                json.dump(reference, f, indent=2)
            print(f"  {source_id}: {reference['goal']['name']}")
        else:
            print(f"  {source_id}: SKIPPED (directory not found)")

    print(f"\nGenerated {len(SDG_REFERENCES)} reference files")


if __name__ == "__main__":
    main()
