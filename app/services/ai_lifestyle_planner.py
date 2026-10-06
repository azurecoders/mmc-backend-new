from datetime import datetime, timezone
import json
import logging
import uuid
from typing import Any, Dict, List, Optional
from openai import AsyncOpenAI

from app.core.config import settings
from app.models.consultation import Consultation
from app.models.user import User
from app.schemas.consultation import (
    DayMealPlanItem,
    FoodRestrictionItem,
    PersonalizedDietPlanResponse,
)

logger = logging.getLogger(__name__)

# =====================================================================
# Clinical Nutrition Database & Fallback Rule Engine
# =====================================================================

CLINICAL_NUTRITION_PROFILES: Dict[str, Dict[str, Any]] = {
    "hypertension": {
        "framework": "DASH Protocol (Dietary Approaches to Stop Hypertension)",
        "calories": "1,800 - 2,000 kcal/day",
        "hydration_liters": 2.5,
        "hydration_guidelines": "Drink 250ml upon waking, 1 glass 30 minutes before each meal, and maintain steady hydration throughout the day. Minimize caffeinated beverages.",
        "foods_to_avoid": [
            FoodRestrictionItem(
                food_to_avoid="Table salt & High-Sodium Seasonings (>1,500mg/day)",
                reason="Excess sodium causes fluid retention and constricts arterial vessels, sharply raising systolic and diastolic BP.",
                healthy_substitute="Fresh herbs (basil, oregano, rosemary), garlic powder, lemon zest, and nutritional yeast."
            ),
            FoodRestrictionItem(
                food_to_avoid="Cured, Smoked & Processed Meats (Sausages, Salami, Bacon)",
                reason="High saturated fat and nitrates accelerate vascular stiffness and endothelial inflammation.",
                healthy_substitute="Skinless poultry breast, baked wild salmon, lentils, or organic firm tofu."
            ),
            FoodRestrictionItem(
                food_to_avoid="Pickles, Canned Soups & Commercial Bouillon Cubes",
                reason="Contain concentrated brine with sodium loads frequently exceeding 1,000mg per serving.",
                healthy_substitute="Homemade vegetable broth seasoned with turmeric, ginger, and black pepper."
            ),
            FoodRestrictionItem(
                food_to_avoid="Energy Drinks & Excessive Coffee (>3 cups/day)",
                reason="Adenosine receptor antagonism causes transient acute spikes in peripheral vascular resistance.",
                healthy_substitute="Hibiscus tea (natural mild ACE-inhibiting properties) or decaffeinated green tea."
            ),
        ],
        "meal_plan": [
            DayMealPlanItem(
                day="Day 1 (Monday)",
                theme="Cardio-Protective Potassium Kickstart",
                breakfast="Steel-cut oatmeal (1 cup) with ground flaxseeds, 1 sliced banana, and a pinch of Ceylon cinnamon.",
                lunch="Mediterranean quinoa bowl with baby spinach, cherry tomatoes, cucumbers, grilled chicken breast, and extra virgin olive oil.",
                snack="Handful of unsalted walnuts (30g) and 1 medium crisp green apple.",
                dinner="Herb-baked cod or sea bass (150g) with steamed asparagus, roasted sweet potato wedges, and fresh lemon drizzle.",
                clinical_note="High potassium in bananas and spinach counterbalances sodium uptake and supports endothelial relaxation."
            ),
            DayMealPlanItem(
                day="Day 2 (Tuesday)",
                theme="Magnesium & Antioxidant Infusion",
                breakfast="Poached egg (1-2) on toasted 100% whole grain sourdough with mashed avocado and microgreens.",
                lunch="Spiced lentil soup (dahl) with brown basmati rice and a side of steamed broccoli seasoned with olive oil and cumin.",
                snack="Plain unsweetened low-fat Greek yogurt with fresh blueberries and chia seeds.",
                dinner="Stir-fried tofu with colorful bell peppers, snap peas, and garlic over a bed of steamed red rice.",
                clinical_note="Magnesium in whole grains and seeds promotes smooth vascular muscle dilation."
            ),
            DayMealPlanItem(
                day="Day 3 (Wednesday)",
                theme="Omega-3 Vascular Defense",
                breakfast="Super-seed smoothie: Unsweetened almond milk, frozen berries, spinach, and 1 tbsp hemp seeds.",
                lunch="Warm barley and chickpea salad with roasted beets, arugula, and lemon-tahini dressing (no added salt).",
                snack="Celery sticks and carrot sticks dipped in homemade garlic hummus.",
                dinner="Pan-seared Atlantic salmon fillet (140g) served with wilted Swiss chard and baked butternut squash.",
                clinical_note="Dietary nitrates from beets convert into nitric oxide, promoting arterial vasodilation."
            ),
            DayMealPlanItem(
                day="Day 4 (Thursday)",
                theme="Fiber-Rich Metabolic Balance",
                breakfast="Buckwheat porridge topped with stewed blackberries and unsalted pumpkin seeds.",
                lunch="Turkey breast wrap in a whole wheat tortilla with hummus, sliced cucumber, shredded carrots, and romaine lettuce.",
                snack="Small handful of unsalted almonds (20-25 nuts).",
                dinner="Lentil and vegetable stew with zucchini, carrots, diced tomatoes, and a side of steamed millet.",
                clinical_note="Soluble fiber delays gastric absorption and reduces systemic arterial inflammation."
            ),
            DayMealPlanItem(
                day="Day 5 (Friday)",
                theme="Plant-Forward Cardioprotection",
                breakfast="Avocado toast on rye bread sprinkled with sesame seeds, accompanied by a soft-boiled egg.",
                lunch="Grilled vegetable and black bean plate with brown rice, pico de gallo (low sodium), and cilantro.",
                snack="1 small pear sliced with 1 tbsp unsalted almond butter.",
                dinner="Baked lemon-herb chicken breast with steamed green beans and quinoa pilaf.",
                clinical_note="Monounsaturated fatty acids in avocado promote high-density lipoprotein (HDL) stability."
            ),
            DayMealPlanItem(
                day="Day 6 (Saturday)",
                theme="Flavonoid & Polyphenol Boost",
                breakfast="Rolled oats soaked overnight in unsweetened oat milk with shredded apples, walnuts, and cinnamon.",
                lunch="Tuscan white bean soup (cannellini beans, kale, diced carrots, and rosemary) with 1 slice whole grain bread.",
                snack="Cup of fresh strawberries or mixed raspberries.",
                dinner="Baked trout with roasted cauliflower florets and steamed baby red potatoes (eaten with skin).",
                clinical_note="Anthocyanins from dark berries protect the vascular endothelium from oxidative stress."
            ),
            DayMealPlanItem(
                day="Day 7 (Sunday)",
                theme="Sustained Recovery & Digestibility",
                breakfast="Scrambled eggs with sautéed mushrooms, tomatoes, and baby spinach, served with whole wheat toast.",
                lunch="Warm roasted pumpkin and chickpea bowl topped with toasted sunflower seeds and olive oil dressing.",
                snack="Crisp cucumber slices with homemade tzatziki (Greek yogurt, fresh dill, lemon juice).",
                dinner="Grilled white fish fillet with steamed broccolini, mashed sweet potatoes, and a squeeze of fresh lime.",
                clinical_note="Light evening meal prevents nocturnal gastric pressure and promotes restful restorative sleep."
            ),
        ],
        "physical_activity": [
            "Brisk walking: 30–45 minutes, 5 days per week (heart rate in moderate aerobic zone).",
            "Light resistance training (resistance bands or bodyweight squats/wall push-ups) 2 times per week.",
            "Avoid heavy isometric strain (e.g., maximum load leg presses) that trigger Valsalva maneuvers and spike BP.",
            "Daily 10-minute diaphragmatic breathing or slow deep yoga breathing to stimulate parasympathetic tone."
        ],
        "lifestyle_habits": [
            "Measure morning blood pressure before caffeine, sitting quietly for 5 minutes with arm at heart level.",
            "Aim for 7 to 8 hours of uninterrupted nocturnal sleep; sleep deprivation triggers sympathetic vasoconstriction.",
            "Eliminate tobacco and vaping; nicotine instantly constricts arterioles and accelerates vascular remodeling.",
            "Limit alcohol to zero or maximum 1 standard drink occasionally; alcohol intake directly correlates with elevated BP."
        ],
        "precautions": [
            "If your systolic BP exceeds 180 mmHg or diastolic exceeds 120 mmHg, seek immediate medical attention.",
            "Watch for sudden dizziness, severe throbbing headache, chest discomfort, or blurred vision.",
            "Do not stop or adjust prescribed antihypertensive medication without physician consultation."
        ]
    },
    "diabetes": {
        "framework": "Low-Glycemic Index (Low-GI) & High-Fiber Metabolic Protocol",
        "calories": "1,600 - 1,800 kcal/day",
        "hydration_liters": 2.8,
        "hydration_guidelines": "Drink water generously between meals (2.5 - 3.0 Liters). Well-hydrated kidneys efficiently filter excess blood glucose via urine. Zero sweetened drinks.",
        "foods_to_avoid": [
            FoodRestrictionItem(
                food_to_avoid="Sugar-Sweetened Beverages, Sodas & Packaged Fruit Juices",
                reason="Rapidly absorbed simple sugars cause sharp postprandial glucose spikes and promote hepatic de novo lipogenesis.",
                healthy_substitute="Sparkling water with fresh lime slices, mint-infused iced herbal tea, or black coffee."
            ),
            FoodRestrictionItem(
                food_to_avoid="Refined White Flour Products (White Bread, Pastries, Doughnuts)",
                reason="High glycemic index (>75) triggers rapid carbohydrate breakdown, placing heavy stress on pancreatic beta cells.",
                healthy_substitute="100% stoneground whole wheat, sprouted grain bread (Ezekiel), or almond flour baked goods."
            ),
            FoodRestrictionItem(
                food_to_avoid="Deep-Fried Starches (French Fries, Potato Chips)",
                reason="Combination of oxidized trans/saturated fats and high-GI starch induces prolonged cellular insulin resistance.",
                healthy_substitute="Roasted spiced chickpeas, baked kale chips, or air-popped popcorn."
            ),
            FoodRestrictionItem(
                food_to_avoid="Dried Fruits (Raisins, Dates) & High-Fructose Syrups in bulk",
                reason="High density of concentrated fructose and glucose without sufficient water mass spikes glycemic load.",
                healthy_substitute="Fresh whole berries (blackberries, raspberries, strawberries) with intact dietary fiber."
            ),
        ],
        "meal_plan": [
            DayMealPlanItem(
                day="Day 1 (Monday)",
                theme="Glycemic Stabilization & Fiber Loading",
                breakfast="Scrambled eggs with baby spinach, tomatoes, and 1 slice sprouted grain toast with mashed avocado.",
                lunch="Grilled chicken salad with mixed greens, bell peppers, sliced cucumbers, pumpkin seeds, and olive oil vinaigrette.",
                snack="Handful of raw almonds (25g) with 1 small Persian cucumber.",
                dinner="Baked salmon with steamed broccoli and 1/2 cup cooked quinoa.",
                clinical_note="Combining lean protein with healthy fat blunts postprandial glucose absorption curves."
            ),
            DayMealPlanItem(
                day="Day 2 (Tuesday)",
                theme="Complex Carbohydrates & Micronutrients",
                breakfast="Steel-cut oatmeal (1/2 cup cooked) with unsweetened almond milk, ground chia seeds, and fresh raspberries.",
                lunch="Lentil and vegetable soup with a large side salad of arugula, tomatoes, and grilled tofu.",
                snack="1/2 cup unsweetened Greek yogurt topped with crushed walnuts and cinnamon.",
                dinner="Herb-marinated chicken breast with sautéed zucchini ribbons and roasted cauliflower florets.",
                clinical_note="Ceylon cinnamon enhances cellular glucose uptake and insulin signaling."
            ),
            DayMealPlanItem(
                day="Day 3 (Wednesday)",
                theme="Anti-Inflammatory Low-Carb Nutrition",
                breakfast="Vegetable omelet (mushrooms, onions, peppers) cooked in light olive oil with 1/4 avocado.",
                lunch="Tuna salad made with Greek yogurt and Dijon mustard over crisp romaine hearts and cherry tomatoes.",
                snack="Celery sticks with 1 tablespoon natural peanut butter (no added sugar or palm oil).",
                dinner="Stir-fried lean beef or tempeh with bok choy, broccoli, and mushrooms over cauliflower rice.",
                clinical_note="Cauliflower rice reduces net carbohydrates by 85% compared to white rice."
            ),
            DayMealPlanItem(
                day="Day 4 (Thursday)",
                theme="Legume-Powered Sustained Energy",
                breakfast="Chia seed pudding prepared with unsweetened almond milk, vanilla extract, and blueberries.",
                lunch="Chickpea and cucumber salad with fresh mint, parsley, red onions, lemon juice, and grilled chicken breast.",
                snack="Handful of dry roasted edamame (high protein, low net carb).",
                dinner="Baked white fish fillet with steamed asparagus and 1/3 cup brown basmati rice.",
                clinical_note="High resistant starch in legumes feeds beneficial gut bacteria that produce insulin-sensitizing short-chain fatty acids."
            ),
            DayMealPlanItem(
                day="Day 5 (Friday)",
                theme="Monounsaturated Fat & Muscle Support",
                breakfast="Poached egg on a bed of sautéed kale and sliced avocado, seasoned with black pepper.",
                lunch="Turkey and vegetable lettuce wraps with sesame-ginger dip and sliced radish.",
                snack="1 boiled egg with a pinch of paprika and sliced bell peppers.",
                dinner="Grilled shrimp or tofu skewers with roasted Mediterranean vegetables (eggplant, zucchini, red onion).",
                clinical_note="Adequate protein intake preserves lean muscle mass, the primary tissue responsible for glucose disposal."
            ),
            DayMealPlanItem(
                day="Day 6 (Saturday)",
                theme="Balanced Weekend Nutrition",
                breakfast="Protein-rich smoothie: Unsweetened pea or whey protein, spinach, 1/2 green apple, chia seeds, and water.",
                lunch="Mediterranean bowl: Quinoa (1/3 cup), steamed green beans, kalamata olives, cherry tomatoes, and grilled chicken.",
                snack="Roasted pumpkin seeds (30g).",
                dinner="Baked turkey meatballs in fresh basil tomato sauce served over zucchini noodles.",
                clinical_note="Zucchini noodles eliminate post-dinner glycemic excursions."
            ),
            DayMealPlanItem(
                day="Day 7 (Sunday)",
                theme="Metabolic Reset & Gentle Digestion",
                breakfast="Plain Greek yogurt with 1 tbsp ground flaxseeds and a handful of fresh blackberries.",
                lunch="Hearty vegetable broth with shredded chicken breast, celery, carrots, and spinach.",
                snack="Half an avocado sprinkled with lemon juice and cracked black pepper.",
                dinner="Baked salmon or trout with sautéed spinach and roasted Brussels sprouts.",
                clinical_note="Omega-3 fatty acids lower elevated triglycerides commonly seen in metabolic syndrome."
            ),
        ],
        "physical_activity": [
            "Post-meal walking: Take a brisk 10 to 15-minute walk immediately following your largest meal to clear glucose.",
            "Moderate aerobic activity: 150 minutes per week (cycling, swimming, brisk walking).",
            "Resistance training 2-3 times weekly to increase GLUT-4 glucose transporter density in skeletal muscle."
        ],
        "lifestyle_habits": [
            "Consistent meal timing: Avoid skipping meals to prevent erratic hypoglycemic and hyperglycemic swings.",
            "Nightly foot inspection: Check for small blisters, redness, or pressure marks.",
            "Prioritize stress reduction: Elevated cortisol stimulates gluconeogenesis in the liver, raising fasting glucose."
        ],
        "precautions": [
            "Be alert to hypoglycemia symptoms: Sweating, trembling, dizziness, rapid heartbeat, or confusion (treat with 15g fast-acting carbs if BG < 70 mg/dL).",
            "Monitor blood glucose as advised by your physician before driving or intensive exercise."
        ]
    },
    "uric_acid": {
        "framework": "Low-Purine & Alkaline Renal Clearance Protocol",
        "calories": "1,800 - 2,000 kcal/day",
        "hydration_liters": 3.0,
        "hydration_guidelines": "Abundant hydration is the cornerstone of uric acid management. Drink 3.0 Liters of water daily to dilute serum urate and promote continuous renal excretion of uric acid crystals.",
        "foods_to_avoid": [
            FoodRestrictionItem(
                food_to_avoid="Organ Meats (Liver, Kidneys, Sweetbreads, Brains)",
                reason="Extremely high in cellular purine nucleotides (>400mg purines/100g) which break down directly into uric acid.",
                healthy_substitute="Plant proteins (tofu, tempeh), eggs, low-fat Greek yogurt, or moderate poultry."
            ),
            FoodRestrictionItem(
                food_to_avoid="Shellfish, Sardines, Anchovies, Mackerel & Caviar",
                reason="High-purine seafood directly triggers acute hyperuricemia and crystallizes into painful gouty joints.",
                healthy_substitute="Fresh salmon, tilapia, or cod in moderate portions (100-120g maximum)."
            ),
            FoodRestrictionItem(
                food_to_avoid="Beer, Brewer's Yeast & Distilled Alcoholic Spirits",
                reason="Beer contains brewer's yeast (purines) and ethanol metabolism increases lactic acid, which competitively inhibits renal uric acid excretion.",
                healthy_substitute="Fresh lemon water, tart cherry juice (diluted with water), or sparkling mineral water."
            ),
            FoodRestrictionItem(
                food_to_avoid="High-Fructose Corn Syrup & Sugary Pastries",
                reason="Hepatic metabolism of fructose consumes ATP, leading to rapid ADP generation and accelerated purine nucleotide catabolism into uric acid.",
                healthy_substitute="Fresh tart cherries, strawberries, or whole citrus fruits."
            ),
        ],
        "meal_plan": [
            DayMealPlanItem(
                day="Day 1 (Monday)",
                theme="Urate-Clearing Tart Cherry & Plant Protein Focus",
                breakfast="Rolled oats prepared with low-fat milk or almond milk, topped with 1/2 cup fresh tart cherries and walnuts.",
                lunch="Lentil and vegetable soup with baby spinach, carrots, and 1 slice whole wheat bread.",
                snack="1 cup fresh cherries or blueberries with a glass of lemon water.",
                dinner="Grilled tofu steak seasoned with ginger and garlic, served with brown rice and steamed broccoli.",
                clinical_note="Tart cherry anthocyanins inhibit xanthine oxidase and accelerate urinary urate clearance."
            ),
            DayMealPlanItem(
                day="Day 2 (Tuesday)",
                theme="Alkaline Vegetable Hydration",
                breakfast="Low-fat cottage cheese (1/2 cup) with sliced strawberries and ground flaxseeds.",
                lunch="Mediterranean quinoa bowl with cucumber, diced tomatoes, kalamata olives, and 1 hard-boiled egg.",
                snack="Celery sticks (contains natural 3-n-butylphthalide) with hummus.",
                dinner="Baked skinless chicken breast (100g) with roasted zucchini, bell peppers, and mashed sweet potatoes.",
                clinical_note="Low-fat dairy intake significantly lowers serum uric acid via the uricosuric effects of casein and lactalbumin."
            ),
            DayMealPlanItem(
                day="Day 3 (Wednesday)",
                theme="Anti-Inflammatory Vitamin C Surge",
                breakfast="Green smoothie: Spinach, 1 orange, half a lemon squeezed, water, and 1 tbsp chia seeds.",
                lunch="Vegetarian chili with red kidney beans, tomatoes, corn, and bell peppers, topped with avocado.",
                snack="Handful of raw almonds (20 nuts) and a tall glass of alkaline water.",
                dinner="Herb-baked cod fillet (100g) served with steamed green beans and boiled baby potatoes.",
                clinical_note="Vitamin C competitively inhibits renal reabsorption of uric acid, promoting natural clearance."
            ),
            DayMealPlanItem(
                day="Day 4 (Thursday)",
                theme="Low-Purine Comfort Nutrition",
                breakfast="Scrambled eggs (2) with sautéed mushrooms and tomatoes on whole grain toast.",
                lunch="Whole wheat pasta tossed with olive oil, garlic, steamed broccoli, and low-fat Parmesan.",
                snack="1 crisp green apple sliced with a dollop of peanut butter.",
                dinner="Roasted vegetable and chickpea traybake (carrots, onions, zucchini, chickpeas) with lemon-tahini dressing.",
                clinical_note="Plant-based purines (lentils, beans) do NOT trigger gout flares unlike animal purines."
            ),
            DayMealPlanItem(
                day="Day 5 (Friday)",
                theme="Renal Flushing & Potassium Balance",
                breakfast="Oatmeal with sliced banana, a dash of cinnamon, and low-fat milk.",
                lunch="Fresh vegetable wrap with hummus, cucumbers, shredded carrots, bell peppers, and romaine lettuce.",
                snack="1 cup fresh watermelon or cantaloupe (high water content aiding hydration).",
                dinner="Grilled chicken breast (100g) with steamed cauliflower and brown rice.",
                clinical_note="High-water fruits assist in maintaining high urinary volume throughout the day."
            ),
            DayMealPlanItem(
                day="Day 6 (Saturday)",
                theme="Polyphenol Defense",
                breakfast="Low-fat Greek yogurt with blueberries, unsalted pumpkin seeds, and a splash of pure tart cherry extract.",
                lunch="Minestrone vegetable soup with kidney beans and a small side salad of mixed greens.",
                snack="Carrot sticks with tzatziki sauce made from low-fat yogurt.",
                dinner="Tofu and vegetable stir-fry with snap peas, bell peppers, and baby corn over steamed brown rice.",
                clinical_note="Soy foods like tofu are clinically proven to be safe and protective against gout."
            ),
            DayMealPlanItem(
                day="Day 7 (Sunday)",
                theme="Joint Protection & Hydration Reassurance",
                breakfast="Whole grain sourdough toast with avocado, sliced tomatoes, and a poached egg.",
                lunch="Quinoa salad with cucumbers, parsley, mint, cherry tomatoes, and lemon olive oil dressing.",
                snack="Handful of unsalted walnuts and 1 fresh orange.",
                dinner="Baked salmon fillet (100g) with roasted asparagus spears and steamed sweet corn.",
                clinical_note="Salmon provides anti-inflammatory omega-3s with a much lower purine profile than shellfish."
            ),
        ],
        "physical_activity": [
            "Low-impact aerobic exercise: Swimming, stationary cycling, or walking (avoids excessive joint compression).",
            "Avoid strenuous high-intensity workouts during acute joint tenderness as dehydration spikes uric acid.",
            "Keep joints mobile with daily gentle range-of-motion stretching exercises."
        ],
        "lifestyle_habits": [
            "Drink 1 glass of water right before going to sleep and keep water by the bed; nocturnal dehydration triggers early-morning gout attacks.",
            "Maintain gradual, steady weight management; rapid starvation diets or crash fasting trigger ketoacidosis which spikes uric acid.",
            "Avoid tight-fitting footwear that compresses the first metatarsophalangeal (big toe) joint."
        ],
        "precautions": [
            "If you experience sudden severe joint redness, swelling, warmth, and excruciating pain (gout flare), rest the joint and contact your physician.",
            "Do not start or abruptly stop uric-acid-lowering medications (e.g. Allopurinol) in the middle of an acute attack without doctor guidance."
        ]
    },
    "general": {
        "framework": "Cardiometabolic Whole-Food Longevity Protocol",
        "calories": "1,800 - 2,100 kcal/day",
        "hydration_liters": 2.5,
        "hydration_guidelines": "Drink 2.5 Liters of fresh water distributed evenly across the day. Begin each morning with a glass of warm water.",
        "foods_to_avoid": [
            FoodRestrictionItem(
                food_to_avoid="Ultra-Processed Snack Foods & Commercial Trans Fats",
                reason="Promotes systemic microvascular inflammation and raises LDL cholesterol.",
                healthy_substitute="Unsalted mixed nuts, seeds, and fresh seasonal fruits."
            ),
            FoodRestrictionItem(
                food_to_avoid="Refined White Sugars & Sweetened Syrups",
                reason="Drives insulin spikes, energy crashes, and visceral fat accumulation.",
                healthy_substitute="Raw honey in moderation, fresh berries, or dates."
            ),
            FoodRestrictionItem(
                food_to_avoid="Excessive Sodium & Artificial Preservatives",
                reason="Elevates baseline blood pressure and places stress on kidney filtration.",
                healthy_substitute="Culinary herbs, garlic, ginger, and lemon juice."
            ),
        ],
        "meal_plan": [
            DayMealPlanItem(
                day="Day 1 (Monday)",
                theme="Vitality & Nutrient Density",
                breakfast="Rolled oats with unsweetened almond milk, chia seeds, sliced banana, and a touch of cinnamon.",
                lunch="Grilled chicken breast with mixed garden salad, olive oil dressing, and a side of quinoa.",
                snack="Handful of raw almonds and 1 crisp apple.",
                dinner="Baked white fish with steamed broccoli, garlic green beans, and roasted sweet potatoes.",
                clinical_note="High-fiber whole foods sustain steady mitochondrial energy production."
            ),
            DayMealPlanItem(
                day="Day 2 (Tuesday)",
                theme="Antioxidant & Cellular Defense",
                breakfast="Poached eggs on 100% whole grain toast with smashed avocado and cherry tomatoes.",
                lunch="Lentil and vegetable stew with brown rice and a side of cucumber slices.",
                snack="Unsweetened Greek yogurt with fresh blueberries.",
                dinner="Stir-fried tofu and colorful vegetables (peppers, snap peas, carrots) over steamed brown rice.",
                clinical_note="Plant polyphenols protect against oxidative cellular damage."
            ),
            DayMealPlanItem(
                day="Day 3 (Wednesday)",
                theme="Heart-Healthy Omega-3 Focus",
                breakfast="Spinach, berry, and flaxseed smoothie prepared with unsweetened oat milk.",
                lunch="Tuna and white bean salad with parsley, lemon juice, and extra virgin olive oil.",
                snack="Carrot and celery sticks with homemade hummus.",
                dinner="Grilled salmon fillet with steamed asparagus and baked sweet potato wedges.",
                clinical_note="Omega-3 fatty acids optimize arterial elasticity and cognitive health."
            ),
            DayMealPlanItem(
                day="Day 4 (Thursday)",
                theme="Gut Microbiome Support",
                breakfast="Buckwheat porridge with berries, pumpkin seeds, and a splash of milk.",
                lunch="Turkey wrap in whole wheat tortilla with hummus, sliced cucumbers, and baby spinach.",
                snack="A handful of walnuts and 1 fresh orange.",
                dinner="Hearty vegetable and bean soup with 1 slice sourdough bread.",
                clinical_note="Diverse dietary fibers cultivate a resilient and anti-inflammatory gut flora."
            ),
            DayMealPlanItem(
                day="Day 5 (Friday)",
                theme="Plant-Forward Longevity",
                breakfast="Scrambled eggs with sautéed mushrooms, tomatoes, and spinach.",
                lunch="Quinoa and chickpea salad with cucumbers, kalamata olives, and fresh lemon dressing.",
                snack="1 small pear with 1 tbsp peanut butter.",
                dinner="Herb-marinated chicken breast with roasted Brussels sprouts and brown rice.",
                clinical_note="Lean poultry provides bioavailable essential amino acids for tissue repair."
            ),
            DayMealPlanItem(
                day="Day 6 (Saturday)",
                theme="Weekend Wellness & Balance",
                breakfast="Overnight oats soaked with chia seeds, grated apple, and walnuts.",
                lunch="Minestrone soup with kidney beans, zucchini, and carrots.",
                snack="A small bowl of fresh mixed berries.",
                dinner="Baked trout with steamed cauliflower florets and roasted baby red potatoes.",
                clinical_note="Low-temperature baking preserves heat-sensitive micronutrients."
            ),
            DayMealPlanItem(
                day="Day 7 (Sunday)",
                theme="Restorative Digestion",
                breakfast="Vegetable omelet with sliced avocado on whole wheat toast.",
                lunch="Warm roasted butternut squash and quinoa bowl with pumpkin seeds.",
                snack="Cucumber slices with Greek yogurt tzatziki.",
                dinner="Grilled white fish with steamed green beans and sweet potato mash.",
                clinical_note="Gentle evening meal ensures sound rest and nocturnal metabolic recovery."
            ),
        ],
        "physical_activity": [
            "Aim for at least 150 minutes of moderate aerobic activity (e.g., brisk walking, cycling) per week.",
            "Include 2 sessions of functional strength training or bodyweight exercises weekly.",
            "Take frequent stretch breaks if sitting for prolonged periods during the workday."
        ],
        "lifestyle_habits": [
            "Maintain a consistent sleep-wake schedule aiming for 7-8 hours nightly.",
            "Practice mindful eating: chew slowly and avoid digital screens during meals.",
            "Spend 15-20 minutes daily in natural morning sunlight to support circadian rhythm."
        ],
        "precautions": [
            "Listen to your body and adjust portion sizes according to daily activity levels.",
            "Consult your healthcare provider if you have underlying medical conditions before making drastic changes."
        ]
    }
}

class AILifestylePlannerService:
    @staticmethod
    def _detect_dominant_condition(diagnosis: str, chronic_conditions: List[str]) -> str:
        """
        Maps clinical diagnosis and patient chronic conditions to dominant nutrition framework.
        """
        combined = f"{diagnosis.lower()} {' '.join(c.lower() for c in chronic_conditions)}"
        if any(term in combined for term in ["uric", "gout", "hyperuricemia", "urate"]):
            return "uric_acid"
        elif any(term in combined for term in ["diabet", "glucose", "glycem", "insulin", "sugar"]):
            return "diabetes"
        elif any(term in combined for term in ["hypertens", "blood pressure", "bp", "cardiac", "heart"]):
            return "hypertension"
        return "general"

    @staticmethod
    async def generate_diet_and_lifestyle_plan(
        patient_name: str,
        diagnosis: str,
        chronic_conditions: Optional[List[str]] = None,
        allergies: Optional[List[str]] = None,
        dietary_preferences: Optional[str] = None,
        consultation_id: Optional[uuid.UUID] = None,
        patient_age: Optional[int] = None,
        patient_gender: Optional[str] = None,
    ) -> PersonalizedDietPlanResponse:
        """
        Generates a tailored 7-day personalized meal guide, foods to avoid, and hydration targets.
        Uses OpenAI gpt-4o-mini with low token consumption (~900 tokens).
        Gracefully falls back to deterministic clinical nutrition protocol if OpenAI API key is unavailable.
        """
        chronic_list = chronic_conditions or []
        allergy_list = allergies or []
        dominant_category = AILifestylePlannerService._detect_dominant_condition(diagnosis, chronic_list)
        fallback_data = CLINICAL_NUTRITION_PROFILES.get(dominant_category, CLINICAL_NUTRITION_PROFILES["general"])

        api_key = settings.OPENAI_API_KEY
        if api_key and api_key.strip():
            try:
                client = AsyncOpenAI(api_key=api_key)
                system_prompt = (
                    "You are an expert Clinical Dietitian, Preventive Cardiologist, and Medical Nutritionist. "
                    "You generate evidence-based, actionable, culturally inclusive 7-day diet and lifestyle care plans "
                    "tailored specifically to the patient's finalized medical diagnosis and chronic profile. "
                    "Output STRICT JSON format matching the schema."
                )

                user_prompt = f"""
Patient Name: {patient_name}
Finalized Clinical Diagnosis: {diagnosis}
Chronic Health Conditions: {', '.join(chronic_list) if chronic_list else 'None reported'}
Known Allergies: {', '.join(allergy_list) if allergy_list else 'None reported'}
Dietary Preferences: {dietary_preferences or 'Standard balanced diet'}
Age: {patient_age or 'Adult'} | Gender: {patient_gender or 'Unspecified'}

Generate a clinically validated personalized lifestyle and nutrition plan in JSON:
{{
  "dietary_framework": "Name of clinical nutrition framework (e.g., DASH, Low-Purine, Low-GI)",
  "daily_calorie_target": "Estimated daily calorie range (e.g., 1,800 - 2,000 kcal)",
  "daily_hydration_liters": 2.5,
  "hydration_guidelines": "Actionable instructions on when and how to hydrate (taking into account kidney/heart health)",
  "foods_to_avoid": [
    {{
      "food_to_avoid": "Specific food item or category",
      "reason": "Pathophysiological reason why it harms this patient condition",
      "healthy_substitute": "Safe, delicious culinary substitute"
    }}
  ],
  "seven_day_meal_plan": [
    {{
      "day": "Day 1 (Monday)",
      "theme": "Daily clinical focus (e.g., Potassium Loading, Low Glycemic Balance)",
      "breakfast": "Detailed breakfast meal with portions",
      "lunch": "Detailed lunch meal with portions",
      "snack": "Healthy snack",
      "dinner": "Light, easily digestible dinner",
      "clinical_note": "Why this specific day helps the patient's condition"
    }}
    ... provide all 7 days from Day 1 to Day 7
  ],
  "physical_activity_plan": [
    "Specific safe cardio/strength exercises",
    "Duration and frequency",
    "Precautions"
  ],
  "lifestyle_and_sleep_habits": [
    "Sleep schedule and sleep hygiene",
    "Stress/circadian rhythm guidelines",
    "Meal timing rules"
  ],
  "clinical_precautions": [
    "Key warning signs or red flags requiring immediate physician visit"
  ]
}}
Ensure foods to avoid have at least 3-4 distinct items. Ensure seven_day_meal_plan has exactly 7 complete daily menus.
"""

                response = await client.chat.completions.create(
                    model=settings.OPENAI_MODEL,  # gpt-4o-mini
                    messages=[
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": user_prompt},
                    ],
                    response_format={"type": "json_object"},
                    temperature=0.2,
                    max_tokens=1800,
                )

                content = response.choices[0].message.content or "{}"
                data = json.loads(content)

                # Parse and return
                return PersonalizedDietPlanResponse(
                    consultation_id=consultation_id,
                    diagnosis=diagnosis,
                    patient_name=patient_name,
                    target_conditions=[diagnosis] + [c for c in chronic_list if c.lower() != diagnosis.lower()],
                    dietary_framework=data.get("dietary_framework", fallback_data["framework"]),
                    daily_calorie_target=data.get("daily_calorie_target", fallback_data["calories"]),
                    daily_hydration_liters=float(data.get("daily_hydration_liters", fallback_data["hydration_liters"])),
                    hydration_guidelines=data.get("hydration_guidelines", fallback_data["hydration_guidelines"]),
                    foods_to_avoid=[FoodRestrictionItem(**item) for item in data.get("foods_to_avoid", [])] or fallback_data["foods_to_avoid"],
                    seven_day_meal_plan=[DayMealPlanItem(**item) for item in data.get("seven_day_meal_plan", [])] or fallback_data["meal_plan"],
                    physical_activity_plan=data.get("physical_activity_plan", fallback_data["physical_activity"]),
                    lifestyle_and_sleep_habits=data.get("lifestyle_and_sleep_habits", fallback_data["lifestyle_habits"]),
                    clinical_precautions=data.get("clinical_precautions", fallback_data["precautions"]),
                    ai_model_used=f"{settings.OPENAI_MODEL} (Live Clinical AI)",
                    is_live_ai=True,
                    generated_at=datetime.now(timezone.utc),
                )
            except Exception as e:
                logger.warning(
                    f"OpenAI diet plan generation error: {e}. Falling back to deterministic clinical nutrition engine."
                )

        # Fallback Deterministic Response
        return PersonalizedDietPlanResponse(
            consultation_id=consultation_id,
            diagnosis=diagnosis,
            patient_name=patient_name,
            target_conditions=[diagnosis] + [c for c in chronic_list if c.lower() != diagnosis.lower()],
            dietary_framework=fallback_data["framework"],
            daily_calorie_target=fallback_data["calories"],
            daily_hydration_liters=fallback_data["hydration_liters"],
            hydration_guidelines=fallback_data["hydration_guidelines"],
            foods_to_avoid=fallback_data["foods_to_avoid"],
            seven_day_meal_plan=fallback_data["meal_plan"],
            physical_activity_plan=fallback_data["physical_activity"],
            lifestyle_and_sleep_habits=fallback_data["lifestyle_habits"],
            clinical_precautions=fallback_data["precautions"],
            ai_model_used="Hospital Clinical Nutrition Rule Engine (Deterministic Protocol)",
            is_live_ai=False,
            generated_at=datetime.now(timezone.utc),
        )


ai_lifestyle_planner = AILifestylePlannerService()
