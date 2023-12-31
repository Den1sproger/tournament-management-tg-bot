import logging

from aiogram import types
from data_processing import (Rating,
                             FAST,
                             STANDART,
                             SLOW,
                             Collection,
                             Comparison,
                             Users)
from ..bot_config import dp
from ..keyboards import get_tourn_type_ikb, get_ikb_gs_url
from googlesheets import RATING_SPREADSHEET_URL
from database import (Database,
                      PROMPT_RESET_OVERALL_RATING,
                      get_prompt_view_games_id,
                      get_prompt_delete_answers,
                      get_prompt_delete_rating,
                      get_prompt_delete_games,
                      get_prompt_delete_games,
                      get_prompt_delete_rating,
                      get_prompt_register_participant)



def get_tourn_class(tourn_type: str,
                    games_data: dict = None) -> FAST | STANDART | SLOW:
    if tourn_type == 'FAST':
        return FAST(games_data=games_data)
    elif tourn_type == 'STANDART':
        return STANDART(games_data=games_data)
    else:
        return SLOW(games_data=games_data)
    

@dp.callback_query_handler(lambda callback: callback.data == 'confirm_finish')
async def confirm_finish(callback: types.CallbackQuery) -> None:
    await callback.message.answer(
        text='Выберите тип турнира',
        reply_markup=get_tourn_type_ikb(action='finish')
    )


@dp.callback_query_handler(lambda callback: callback.data == 'not_confirm')
async def delete_confirm_msg(callback: types.CallbackQuery) -> None:
    await callback.message.delete()


@dp.callback_query_handler(lambda callback: callback.data.endswith('_type_finish'))
async def select_type_finish(callback: types.CallbackQuery) -> None:
    try:
        tourn_type = callback.data.replace('_type_finish', '').upper()
        db = Database()
        db.action(
            get_prompt_delete_rating(tourn_type),
            get_prompt_delete_answers(tourn_type),
            get_prompt_delete_games(tourn_type)
        )
        games_gs = get_tourn_class(tourn_type)
        games_gs.clear_table()
        
    except FileNotFoundError:
        pass
    except Exception as _ex:
        logging.error(_ex)
        await callback.message.answer("❌❌Ошибка❌❌")
        return
    
    await callback.message.answer(f'✅Турниры {tourn_type} завершены')
    await callback.message.delete()


@dp.callback_query_handler(lambda callback: callback.data.endswith('_type_fill'))
async def select_type_fill(callback: types.CallbackQuery) -> None:
    # parsing sport games and recorde to json
    try:
        tourn_type = callback.data.replace('_type_fill', '').upper()
        
        db = Database()
        games = db.get_data_list(get_prompt_view_games_id(tourn_type))
        if games:
            await callback.message.answer(f'У вас уже заполнены матчи по {tourn_type}')
            return
        
        parser = Collection(get_full_data=True, tourn_type=tourn_type)
        admin_data = parser.log_in()
        parser.get_games(id=admin_data['id'], hash=admin_data['hash'])
        parser.get_begin_time()
        parser.get_game_url()
        parser.get_team_coeffs()
        parser.recorde_to_json()
        parser.session.close()

        # writing data to the googlesheet
        gs = get_tourn_class(tourn_type, games_data=parser.full_data)
        gs.write_data()
    except Exception as _ex:
        logging.error(_ex)
        await callback.message.answer("❌❌Ошибка❌❌")
        return
    
    await callback.message.answer(
        text="Таблица заполнена✅",
        reply_markup=get_ikb_gs_url(
            button_text=gs.SHEET_NAME,
            url=gs.URL
        )
    )


@dp.callback_query_handler(lambda callback: callback.data.endswith('_type_clear'))
async def select_type_clear(callback: types.CallbackQuery) -> None:
    try:
        tourn_type = callback.data.replace('_type_clear', '').upper()
        gs = get_tourn_class(tourn_type)
        gs.clear_table()
        db = Database()
        db.action(get_prompt_delete_games(tourn_type))
    except FileNotFoundError:
        pass
    except Exception as _ex:
        logging.error(_ex)
        await callback.message.answer("❌❌Ошибка❌❌")
        return
    
    await callback.message.answer(
        text=f"Таблица {tourn_type} очищена✅",
        reply_markup=get_ikb_gs_url(
            button_text=gs.SHEET_NAME,
            url=gs.URL
        )
    )


@dp.callback_query_handler(lambda callback: callback.data.endswith('_type_add'))
async def add_rating(callback: types.CallbackQuery) -> None:
    tourn_type = callback.data.replace('_type_add', '').upper()

    try:
        # get the tournament's users of the tournament type
        comparsion = Comparison()
        users_tournaments = comparsion.get_tournaments(tourn_type)
        
        # write data to the table with name "current rating"
        rating = Rating(tourn_type)
        rating.add_rating(users_tournaments)

        # write data to the database to the table with name "participants"
        db = Database()
        queries = [get_prompt_delete_rating(tourn_type)]
        for item in users_tournaments:
            queries.append(
                get_prompt_register_participant(
                    nickname=item[0],
                    tournament=item[-1]
                )
            )
            
        db.action(*queries)
    except Exception as _ex:
        logging.info(_ex)
        await callback.message.answer("❌❌Ошибка❌❌")
    else:
        await callback.message.answer(
            text=f'✅Текущий рейтинг {tourn_type} создан',
            reply_markup=get_ikb_gs_url(
                button_text=Rating.SHEET_NAME,
                url=RATING_SPREADSHEET_URL
            )
        )


@dp.callback_query_handler(lambda callback: callback.data.endswith('_type_approve'))
async def add_rating(callback: types.CallbackQuery) -> None:
    try:
        tourn_type = callback.data.replace('_type_approve', '').upper()
        gs = get_tourn_class(tourn_type)
        gs.approve_tournament_games()
        parser = Collection(tourn_type)
        parser.write_to_database()
    except Exception as _ex:
        logging.error(_ex)
        await callback.message.answer("❌❌Ошибка❌❌")
    else:
        await callback.message.answer(
            f"Данные {tourn_type} утверждены✅\nДля корректной работы ничего не меняйте в таблице"
        )


@dp.callback_query_handler(lambda callback: callback.data == 'confirm_reset')
async def confirm_reset(callback: types.CallbackQuery) -> None:
    try:
        db = Database()
        db.action(PROMPT_RESET_OVERALL_RATING)
        
        users = Users()
        users.update_scores()

    except Exception as _ex:
        logging.error(_ex)
        await callback.message.answer("❌❌Ошибка❌❌")
    else:
        await callback.answer('Рейтинг обнулен✅')
        await callback.message.delete()


@dp.callback_query_handler(lambda callback: callback.data == 'not_confirm_reset')
async def confirm_reset(callback: types.CallbackQuery) -> None:
    await callback.message.delete()
    