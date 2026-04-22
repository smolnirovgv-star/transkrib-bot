# Test Environment — Transkrib

Эта ветка (test) — тестовое окружение для экспериментов.

## Критические правила
- НЕ мержить в main без полного тестирования.
- Не трогать prod credentials (YOOKASSA, prod bot token).
- Для Supabase: использовать таблицы с префиксом test_
  (test_bot_users, test_invite_codes, test_long_video_sessions и т.д.)

## Окружения
| | Prod | Test |
|---|---|---|
| Telegram bot | @transkrib_smartcut_bot | @transkrib_test_bot |
| GitHub branch | main | test |
| Railway services | transkrib-bot / transkrib-api | transkrib-bot-test / transkrib-api-test |
| Supabase tables | bot_users, invite_codes | test_bot_users, test_invite_codes |

## Фокус разработки
1. Почасовой режим для длинных видео (>1 час):
   - разбиение на части ~1 час
   - пауза после каждого часа, показ результата
   - запрос согласия пользователя
   - состояние в test_long_video_sessions
2. Умные границы чанков (по смыслу, не по паузам Whisper)
3. Плавные переходы между склеенными фрагментами
4. Устранение TIMEOUT на видео >30 минут

## Safe rollback
Если сломал test — вернись к prod:
  git checkout main

Если сломал main (не должно произойти) — откат:
  git checkout epoch/full-pipeline-with-payments-2026-04-22
