// GENERATED from brain/intents.yaml by mobile/gen_intents.py. Do not edit by hand.
// ignore_for_file: lines_longer_than_80_chars

import 'router.dart';

const List<Intent> kIntents = [
  Intent(name: "greeting", clip: "greeting", say: "Hello! How can I help you?", fuzzy: true, templates: ["hello", "hi", "hey", "hello pecko", "hi pecko", "hey pecko", "good morning", "good afternoon", "good evening", "hello there", "hi there", "hey there"]),
  Intent(name: "thanks", clip: "thanks", say: "You're welcome!", fuzzy: true, templates: ["thanks", "thank you", "thank you so much", "thanks a lot", "thanks pecko", "thank you pecko", "many thanks"]),
  Intent(name: "bye", clip: "bye", say: "Goodbye! Talk to you soon.", fuzzy: true, templates: ["bye", "goodbye", "bye bye", "see you", "see you later", "good night", "talk to you later"]),
  Intent(name: "how_are_you", clip: "how_are_you", say: "I'm doing well, thank you. How are you?", fuzzy: true, templates: ["how are you", "how are you doing", "how are you today", "how's it going", "how do you do", "what's up"]),
  Intent(name: "who_are_you", clip: "who_are_you", say: "I'm Pecko, a voice assistant that runs entirely on this device.", fuzzy: true, templates: ["who are you", "who is this", "what are you", "tell me about yourself", "introduce yourself"]),
  Intent(name: "your_name", clip: "your_name", say: "My name is Pecko.", fuzzy: true, templates: ["what is your name", "what's your name", "your name", "tell me your name", "what do they call you"]),
  Intent(name: "what_can_you_do", clip: "what_can_you_do", say: "I can chat, answer simple questions, and tell you the time and date, all without internet.", fuzzy: true, templates: ["what can you do", "what do you do", "what are you able to do", "how can you help me", "what are your features"]),
  Intent(name: "who_made_you", clip: "who_made_you", say: "I was built by team Plumbers for HackNEX 2026.", fuzzy: true, templates: ["who made you", "who built you", "who created you", "who programmed you", "who is your creator"]),
  Intent(name: "are_you_online", clip: "are_you_online", say: "No, I work completely offline. Nothing leaves this device.", fuzzy: true, templates: ["are you online", "do you need internet", "do you use the internet", "are you connected to the internet", "do you work offline"]),
  Intent(name: "are_you_ai", clip: "are_you_ai", say: "Yes, I'm an AI assistant, not a person.", fuzzy: true, templates: ["are you a robot", "are you an ai", "are you human", "are you a real person", "are you a machine"]),
  Intent(name: "are_you_listening", clip: "are_you_listening", say: "Yes, I'm here and listening.", fuzzy: true, templates: ["are you listening", "can you hear me", "are you there", "do you hear me", "are you awake"]),
  Intent(name: "help", clip: "help", say: "Sure. Just ask me a question or tell me what you need.", fuzzy: true, templates: ["help", "help me", "i need help", "can you help me", "i need some help"]),
  Intent(name: "weather", clip: "weather", say: "I can't check the weather because I work offline.", fuzzy: true, templates: ["what's the weather", "how's the weather", "what is the weather today", "will it rain today", "what's the temperature outside", "is it going to rain"]),
  Intent(name: "news", clip: "news", say: "I can't read the news because I work offline.", fuzzy: true, templates: ["what's the news", "tell me the news", "read the news", "any news today", "what's happening in the news"]),
  Intent(name: "music", clip: "music", say: "I can't play music yet. I can only talk.", fuzzy: true, templates: ["play music", "play a song", "play some music", "put on some music", "sing a song"]),
  Intent(name: "alarm", clip: "alarm", say: "I can't set alarms or timers yet.", fuzzy: true, templates: ["set an alarm", "set a timer", "wake me up", "set an alarm for tomorrow", "start a timer"]),
  Intent(name: "call", clip: "call", say: "I can't make calls or send messages.", fuzzy: true, templates: ["call someone", "make a call", "send a message", "send a text", "phone my friend"]),
  Intent(name: "shopping", clip: "shopping", say: "I can't order or buy things, since I work offline.", fuzzy: true, templates: ["order food", "buy something", "order a pizza", "shop online", "book a ticket"]),
  Intent(name: "joke", clip: "joke", say: "Why did the computer get cold? It left its Windows open.", fuzzy: true, templates: ["tell me a joke", "say a joke", "make me laugh", "got any jokes", "joke"]),
  Intent(name: "compliment", clip: "compliment", say: "Thank you, that's kind of you!", fuzzy: true, templates: ["you are smart", "you're smart", "you are great", "good job", "well done", "you are awesome", "you're awesome", "you're amazing"]),
  Intent(name: "sorry", clip: "sorry", say: "No problem at all.", fuzzy: true, templates: ["sorry", "i'm sorry", "my bad", "excuse me", "pardon me"]),
  Intent(name: "ok_ack", clip: "ok_ack", say: "Okay.", fuzzy: false, templates: ["ok", "okay", "alright", "all right", "got it", "i see", "sure", "fine", "cool", "great"]),
  Intent(name: "never_mind", clip: "never_mind", say: "Okay, never mind.", fuzzy: true, templates: ["never mind", "nevermind", "forget it", "cancel that", "ignore that", "stop"]),
  Intent(name: "how_old", clip: "how_old", say: "I'm brand new, built just for this hackathon.", fuzzy: true, templates: ["how old are you", "what is your age", "when were you born", "when were you made"]),
  Intent(name: "where_running", clip: "where_running", say: "I'm running right here on your device, using only the CPU.", fuzzy: true, templates: ["where are you running", "where do you live", "where are you", "where are you running from", "which device are you on"]),
  Intent(name: "languages", clip: "languages", say: "I mostly speak English for now.", fuzzy: true, templates: ["what languages do you speak", "which languages do you know", "do you speak tamil", "do you speak hindi", "can you speak other languages"]),
  Intent(name: "what_is_pecko", clip: "what_is_pecko", say: "Pecko is an offline voice assistant that runs on a small CPU with no internet.", fuzzy: true, templates: ["what is pecko", "what does pecko mean", "tell me about pecko", "what's pecko"]),
  Intent(name: "repeat_unsupported", clip: "repeat_unsupported", say: "Sorry, I can't repeat that, but you can ask me again.", fuzzy: true, templates: ["repeat that", "say that again", "what did you say", "can you repeat that", "repeat please", "come again"]),
  Intent(name: "didnt_catch", clip: "didnt_catch", say: "Sorry, I didn't catch that. Could you say it again?", fuzzy: false, templates: ["huh", "what", "hmm", "uh"]),
  Intent(name: "low_power", clip: "low_power", say: "I'm in low-power mode right now, so I can only do simple things like the time and date.", fuzzy: false, templates: ["low power mode", "are you in low power mode"]),
];
