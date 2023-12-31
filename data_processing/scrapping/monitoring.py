import string
import logging
import time

from gspread.exceptions import APIError
from gspread.worksheet import Worksheet
from gspread.spreadsheet import Spreadsheet
from database import (Database_Thread,
                      TOURNAMENT_TYPES,
                      get_prompt_view_games_id,
                      get_prompt_update_status,
                      get_prompt_view_users_by_answer,
                      get_prompt_add_scores,
                      get_prompt_view_game_coeffs,
                      get_prompt_view_nick_by_id)
from .parser import Parser
from ..sheets_work.participants import Users
from ..sheets_work.games import FAST, STANDART, SLOW



class Monitoring(Parser):
    """Monitoring the games and update data in database"""

    CELLS_COLS = {
        "nickname": "A",
        "score": "B",
        "tourn_type": "C"
    }
    LENGTH = len(CELLS_COLS)
    BETWEEN = 1
    OFFSET = LENGTH + BETWEEN
    SHEET_NAME = 'Текущий рейтинг'
    

    def __init__(self, *tourn_types) -> None:
        for tt in tourn_types:
            assert tt in TOURNAMENT_TYPES, 'Unknown tournament type'
        self.tournament_types = tourn_types

        super().__init__()
        self.worksheet = Monitoring.get_ws(self.spreadsheet)
        self.cells = string.ascii_uppercase
        

    @staticmethod
    def get_ws(spreadsheet: Spreadsheet, retry: int = 5) -> Worksheet:
        try:
            ws = spreadsheet.worksheet(Monitoring.SHEET_NAME)
        except (APIError, Exception) as _ex:
            if retry:
                logging.info(f'retry={retry} => worksheet {_ex}')
                retry -= 1
                time.sleep(5)
                return Monitoring.get_ws(spreadsheet=spreadsheet, retry=retry)
            else:
                raise
        return ws
    

    @staticmethod
    def update_scores(worksheet: Worksheet,
                      update_data: list[dict[str]],
                      retry: int = 5) -> None:
        try:
            worksheet.batch_update(update_data)
        except (APIError, Exception) as _ex:
            if retry:
                logging.info(f'retry={retry} => update_scores {_ex}')
                retry -= 1
                time.sleep(5)
                Monitoring.update_scores(
                    worksheet=worksheet, update_data=update_data, retry=retry
                )
            else:
                raise


    @staticmethod
    def get_col_values(worksheet: Worksheet,
                       col_number: int,
                       retry: int = 5) -> list[str]:
        try:
            col_values = worksheet.col_values(col_number)
        except (APIError, Exception) as _ex:
            if retry:
                logging.info(f'retry={retry} => col_values {_ex}')
                retry -= 1
                time.sleep(5)
                return Monitoring.get_col_values(
                    worksheet=worksheet, col_number=col_number, retry=retry
                )
            else:
                raise
        return col_values
    

    @staticmethod
    def get_cells_data(worksheet: Worksheet,
                       cells_range: str,
                       retry: int = 5) -> list:
        try:
            col_values = worksheet.get(cells_range)
        except (APIError, Exception) as _ex:
            if retry:
                logging.info(f'retry={retry} => get cells data {_ex}')
                retry -= 1
                time.sleep(5)
                return Monitoring.get_cells_data(
                    worksheet=worksheet, cells_range=cells_range, retry=retry
                )
            else:
                raise
        return col_values
        

    @staticmethod
    def sort_rating(*specs,
                    worksheet: Worksheet,
                    cells_range: str,
                    retry: int = 5) -> None:
        try:
            worksheet.sort(*specs, range=cells_range)
        except (APIError, Exception) as _ex:
            if retry:
                logging.info(f'retry={retry} => sort rating {_ex}')
                retry -= 1
                time.sleep(5)
                Monitoring.sort_rating(
                    *specs, worksheet=worksheet, cells_range=cells_range, retry=retry
                )
            else:
                raise


    def _get_column(self, column: str, tourn_type: str) -> str:
        if tourn_type == 'FAST':
            return self.CELLS_COLS[column]
        elif tourn_type == 'STANDART':
            return self.cells[self.cells.index(self.CELLS_COLS[column]) + self.OFFSET]
        else:
            return self.cells[self.cells.index(self.CELLS_COLS[column]) + self.OFFSET * 2]


    def _get_tourn_class(self,
                         tourn_type: str,
                         games_data: dict = None) -> FAST | STANDART | SLOW:
        if tourn_type == 'FAST':
            return FAST(games_data=games_data)
        elif tourn_type == 'STANDART':
            return STANDART(games_data=games_data)
        else:
            return SLOW(games_data=games_data)
        

    def check_status(self) -> None | list[str]:
        # main function
        # checking the status of the games and update data in database
        completed_types = []
        db = Database_Thread()
        update_data = []

        for type_ in self.tournament_types:

            games = db.get_data_list(               # get games
                get_prompt_view_games_id(type_)
            )
            if games:
                games_id = [i[0] for i in games]      # get keys of games
                for game in games_id:                                   # games iteration

                    status = self._get_data_time(game, data_key='DA')
                    if status in (2, 3,):                                # if the game time status is not 1

                        db.action(                                      # update game status on 2 or 3
                            get_prompt_update_status(game, status, type_)
                        )
                        if status == 3:                                 # if the game is over
                            
                            result = self.get_winner(game)   # winner
                            table_g = self._get_tourn_class(tourn_type=type_)

                            # color cell
                            if not result:
                                table_g.color_cell(game_key=game, color='red')
                                continue
                            table_g.color_cell(game_key=game, color='green', winner=result)
                            
                            # get coefficients
                            coeffs = db.get_data_list(
                                get_prompt_view_game_coeffs(game)
                            )[0]
                            coeffs = list(coeffs)

                            # get answers
                            answers = db.get_data_list(
                                get_prompt_view_users_by_answer(game, type_)
                            )
                            for answer in answers:                        # game answers iteration
                                
                                if result == answer[1]:            # if user's answer is right
                                    # get the user internal nickname by Telegram chat id 
                                    nickname = db.get_data_list(            
                                        get_prompt_view_nick_by_id(answer[0])
                                    )[0][0]

                                    scores = self.get_scores_by_coeff(coeffs[result - 1])
                                    
                                    # update the user's scoes in the current table in the googlesheets
                                    try:
                                        cell, adding_scores = self.get_cell_add_score(
                                            score=scores, nickname=nickname,
                                            tourn_type=type_,
                                            tournament=answer[-1]
                                        )
                                    except TypeError as _ex:
                                        logging.error(f'scores={scores}\nnickname={nickname}\ntype_={type_}\ntournament={answer[-1]} ', _ex)
                                        continue
                                    
                                    update_data.append({
                                        'range': cell, 'values': [[adding_scores]]
                                    })

                                    # update the user's scores in the participants table in the database
                                    prompts = get_prompt_add_scores(
                                        adding_scores=scores,
                                        nickname=nickname,
                                        tournament=answer[-1]
                                    )
                                    db.action(*prompts)
                            # update scores
                            Monitoring.update_scores(self.worksheet, update_data)

            else:       # tournament is over
                completed_types.append(type_)

        # update rating
        self.update_rating()

        # if the tournament or tournaments are over
        if completed_types:
            users = Users()
            users.update_scores()
            return completed_types


    def get_winner(self, game_id: str) -> int | bool:
        # get the end scores of the teams
        
        data = self._create_game_request(
            url=f'https://local-ruua.flashscore.ninja/46/x/feed/dc_1_{game_id}'
        )
        string = {}
        for item in data:
            key = item.split('÷')[0]
            value = item.split('÷')[-1]
            string[key] = value

        try:
            score_1 = string['DE']
            score_2 = string['DF']
        except Exception as _ex:
            logging.error(_ex)
            return False
        
        if score_1 > score_2:
            return 1        # the first team win
        elif score_1 < score_2:
            return 2        # the second team win
        else:
            return 3        # draw
        

    def get_scores_by_coeff(self, coeff: str) -> int:
        # get the quantity of scores by coefficient
        if not coeff:
            return 0
        coefficient = float(coeff.replace(',', '.'))
        if coefficient < 1.26:
            return 3
        
        count = 126
        switch = 2
        score = 5

        while score < 30:
            interval = [i / 100 for i in range(count, count + 50)]
            if coefficient in interval:
                return score
            count += 50

            if switch == 1:
                score += 2
                switch = 2
            else:
                score += 1
                switch = 1
        else:
            if coefficient >= 9.76:
                return 30
            

    def get_cell_add_score(self,
                           nickname: str,
                           score: int,
                           tourn_type: str,
                           tournament: str) -> str and int:
        # get the cell for the update score of the participant in the table
        participants = Monitoring.get_col_values(
            worksheet=self.worksheet,
            col_number=self.cells.index(self._get_column("nickname", tourn_type)) + 1
        )
        last_row = len(participants)
        cells_range = f"{self._get_column('nickname', tourn_type)}3:" \
                      f"{self._get_column('tourn_type', tourn_type)}{last_row}"
        data = Monitoring.get_cells_data(self.worksheet, cells_range)

        for item in data:
            if item[0] == nickname and item[-1] == tournament:
                old_scores = int(item[1]) 
                row = data.index(item) + 3
                return f"{self._get_column('score', tourn_type)}{row}", old_scores + score


    def update_rating(self):
        # update the sheet with the raiting of the participants'

        for type_ in self.tournament_types:
            first_column = self._get_column("nickname", type_)
            last_row = len(
                Monitoring.get_col_values(
                    worksheet=self.worksheet,
                    col_number=self.cells.index(first_column) + 1
                )
            )
            cells_range = f'{first_column}3:' \
                          f'{self._get_column("tourn_type", type_)}{last_row}'
            
            Monitoring.sort_rating(
                (self.cells.index(self._get_column("tourn_type", type_)) + 1, 'des'),
                (self.cells.index(self._get_column("score", type_)) + 1, 'des'),
                worksheet=self.worksheet,
                cells_range=cells_range
            )

        
