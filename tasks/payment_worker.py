import asyncio
import logging

from database import fetch, fetchrow, execute
from bot import bot
from handlers.page import send_page


async def payment_worker():

    logging.info("💳 Payment worker running...")


    while True:

        try:

            payments = await fetch(
                """
                SELECT
                    id,
                    user_id,
                    code,
                    invoice_id,
                    seller_paid
                FROM payments
                WHERE status='paid'
                  AND type='file'
                LIMIT 20
                """
            )


            for p in payments:

                try:

                    # =========================
                    # CEK FILE
                    # =========================

                    file = await fetchrow(
                        """
                        SELECT
                            owner_id,
                            price
                        FROM files
                        WHERE LOWER(TRIM(code))
                              =
                              LOWER(TRIM($1))
                        LIMIT 1
                        """,
                        p["code"]
                    )


                    if not file:

                        logging.warning(
                            "File tidak ditemukan %s",
                            p["code"]
                        )

                        continue



                    # =========================
                    # KIRIM FILE KE BUYER
                    # =========================

                    sent = await send_page(
                        bot=bot,
                        chat_id=p["user_id"],
                        user_id=p["user_id"],
                        code=p["code"],
                        page=1
                    )


                    if not sent:

                        logging.warning(
                            "Gagal kirim file %s",
                            p["code"]
                        )

                        continue



                    # =========================
                    # SIMPAN PEMBELIAN
                    # =========================

                    purchase = await fetchrow(
                        """
                        SELECT id
                        FROM file_purchases
                        WHERE payment_id=$1
                        LIMIT 1
                        """,
                        p["invoice_id"]
                    )


                    if not purchase:

                        await execute(
                            """
                            INSERT INTO file_purchases(
                                user_id,
                                file_code,
                                owner_id,
                                paid_price,
                                payment_id,
                                status,
                                paid_at
                            )
                            VALUES(
                                $1,$2,$3,$4,$5,
                                'paid',
                                NOW()
                            )
                            ON CONFLICT (user_id, file_code) DO NOTHING
                            """,
                            p["user_id"],
                            p["code"],
                            file["owner_id"],
                            file["price"],
                            p["invoice_id"]
                        )


                        logging.info(
                            "🛒 Purchase saved %s",
                            p["code"]
                        )



                    # =========================
                    # BAYAR SELLER 50%
                    # =========================

                    if not p["seller_paid"]:

                        seller_id = file["owner_id"]
                        price = file["price"] or 0


                        seller_earn = int(
                            price * 0.5
                        )


                        if seller_id and seller_earn > 0:


                            await execute(
                                """
                                UPDATE users
                                SET
                                    balance =
                                    balance + $1,

                                    total_earn =
                                    total_earn + $1

                                WHERE user_id=$2
                                """,
                                seller_earn,
                                seller_id
                            )


                            # log transaksi seller

                            await execute(
                                """
                                INSERT INTO transactions(
                                    user_id,
                                    type,
                                    amount,
                                    description
                                )
                                VALUES(
                                    $1,
                                    'file_sale',
                                    $2,
                                    $3
                                )
                                """,
                                seller_id,
                                seller_earn,
                                f"Pendapatan file {p['code']}"
                            )


                            logging.info(
                                "💰 Seller +Rp%s user=%s",
                                seller_earn,
                                seller_id
                            )



                        await execute(
                            """
                            UPDATE payments
                            SET
                                seller_paid=true
                            WHERE id=$1
                            """,
                            p["id"]
                        )



                    # =========================
                    # SELESAIKAN PAYMENT
                    # =========================

                    await execute(
                        """
                        UPDATE payments
                        SET
                            status='completed',
                            updated_at=NOW()
                        WHERE id=$1
                        """,
                        p["id"]
                    )


                    logging.info(
                        "✅ Payment completed %s",
                        p["invoice_id"]
                    )



                except Exception:

                    logging.exception(
                        "❌ PAYMENT PROCESS ERROR %s",
                        p["invoice_id"]
                    )



        except Exception:

            logging.exception(
                "💥 PAYMENT WORKER ERROR"
            )



        await asyncio.sleep(15)
